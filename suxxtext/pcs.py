"""
Problem / Cause / Solution (PCS) extraction via local Ollama (Gemma).

Designed for Dr. Berg–style health videos: symptom → root cause → concrete fix
(food, exercise, habit). Output is compact JSON for later search / CLI wiring.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from suxxtext.ollama_client import (
    OllamaError,
    default_model,
    generate,
    list_models,
    ollama_host,
    ping,
)
from suxxtext.paths import CHANNELS_ROOT

# YouTube video ids are 11 chars; transcript names usually end with _ID.txt
VIDEO_ID_RE = re.compile(r"([A-Za-z0-9_-]{11})\.txt$")

# ~40 words × 1.15 ≈ 46; allow a little headroom for natural phrasing
FIELD_WORD_BUDGET = 50

SYSTEM_PROMPT = """You are a precise medical-content extractor for Dr. Eric Berg style health videos.
Your job is NOT to invent advice. Extract only what the speaker claims.

Return ONLY a JSON object (no markdown, no commentary) with this shape:
{
  "problem": "main symptom or condition (a bit fuller than a headline)",
  "cause": "root cause the speaker attributes, with enough mechanism to be useful",
  "solution": "concrete fix: food to eat/avoid, exercise, dose/habit, or protocol",
  "symptoms": ["search", "keywords"],
  "related": ["adjacent topics, side effects, related conditions, or linked tips from the talk"]
}

Rules:
- Fluff-free but not telegraphic. Each of problem / cause / solution should be about
  45–50 words max (roughly 15% more detail than a one-liner). Prefer one tight
  sentence or two short ones; include key numbers, foods, or steps when the speaker
  gives them.
- solution must be actionable (eat X, stop Y, do Z, supplement W) when the speaker gives one.
- related: 2–8 short phrases for ADJACENT content — side mentions, related conditions,
  caveats, "also covers", industry myths debunked, or natural next topics a viewer
  with this problem would care about. Prefer phrases grounded in the transcript;
  if the talk clearly implies an adjacent angle, you may note it briefly. Empty list
  only if nothing adjacent appears.
- If the speaker covers multiple independent problems, use:
  {"items": [{"problem":"...","cause":"...","solution":"...","symptoms":[...],"related":[...]}, ...]}
  Max 5 items; put the primary topic first. related on each item is local to that tip;
  you may also put shared adjacent themes on the primary item.
- symptoms: 2–8 short keywords a patient might search (e.g. bloating, gout, fatigue).
- If the transcript is empty or not health advice, still fill the three fields honestly
  (e.g. problem: "unclear / not health advice") and related: [].
"""

USER_TEMPLATE = """Extract problem / cause / solution / related from this transcript.

Title: {title}
Video id: {video_id}

--- TRANSCRIPT START ---
{transcript}
--- TRANSCRIPT END ---
"""


def _str_list(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        return [s.strip() for s in re.split(r"[,;|]", raw) if s.strip()]
    if isinstance(raw, list):
        return [str(s).strip() for s in raw if str(s).strip()]
    return []


@dataclass
class PCSItem:
    problem: str
    cause: str
    solution: str
    symptoms: List[str] = field(default_factory=list)
    related: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "problem": self.problem.strip(),
            "cause": self.cause.strip(),
            "solution": self.solution.strip(),
            "symptoms": [s.strip() for s in self.symptoms if str(s).strip()],
            "related": [s.strip() for s in self.related if str(s).strip()],
        }


@dataclass
class PCSRecord:
    video_id: str
    title: str
    channel: str
    source_transcript: str
    model: str
    created_at: str
    items: List[PCSItem]
    raw_response: Optional[str] = None

    def primary(self) -> PCSItem:
        return self.items[0] if self.items else PCSItem("", "", "")

    def to_dict(self) -> Dict[str, Any]:
        primary = self.primary()
        d: Dict[str, Any] = {
            "video_id": self.video_id,
            "title": self.title,
            "channel": self.channel,
            "source_transcript": self.source_transcript,
            "model": self.model,
            "created_at": self.created_at,
            # flat primary fields for easy search / grepping
            "problem": primary.problem,
            "cause": primary.cause,
            "solution": primary.solution,
            "symptoms": primary.symptoms,
            "related": primary.related,
            "items": [i.to_dict() for i in self.items],
        }
        return d

    def search_blob(self) -> str:
        """Single lowercase string for naive symptom search."""
        parts: List[str] = []
        for it in self.items:
            parts.extend(
                [it.problem, it.cause, it.solution, *it.symptoms, *it.related]
            )
        return " ".join(parts).lower()


def video_id_from_transcript_path(path: str | Path) -> Optional[str]:
    name = Path(path).name
    m = VIDEO_ID_RE.search(name)
    if m:
        return m.group(1)
    # fallback: any 11-char token in name
    found = re.findall(r"[A-Za-z0-9_-]{11}", name)
    return found[-1] if found else None


def title_from_transcript_path(path: str | Path, video_id: Optional[str] = None) -> str:
    name = Path(path).stem
    # drop leading date like 18-Jul-2026-
    name = re.sub(r"^\d{1,2}-[A-Za-z]{3}-\d{4}-", "", name)
    # drop trailing view counts: _261000views
    name = re.sub(r"_\d+views?", "", name, flags=re.I)
    if video_id and name.endswith("_" + video_id):
        name = name[: -(len(video_id) + 1)]
    elif video_id and name.endswith(video_id):
        name = name[: -len(video_id)].rstrip("_")
    title = name.replace("_", " ").replace("...", "").strip()
    title = re.sub(r"\s+", " ", title)
    return title or Path(path).stem


def _coerce_item(obj: Any) -> Optional[PCSItem]:
    if not isinstance(obj, dict):
        return None
    problem = str(obj.get("problem") or obj.get("Problem") or "").strip()
    cause = str(obj.get("cause") or obj.get("Cause") or "").strip()
    solution = str(obj.get("solution") or obj.get("Solution") or "").strip()
    if not (problem or cause or solution):
        return None
    symptoms = _str_list(obj.get("symptoms") or obj.get("keywords"))
    related = _str_list(
        obj.get("related")
        or obj.get("adjacent")
        or obj.get("related_topics")
        or obj.get("also")
    )
    return PCSItem(
        problem=problem or "(unspecified)",
        cause=cause or "(unspecified)",
        solution=solution or "(unspecified)",
        symptoms=symptoms,
        related=related,
    )


def _loads_json_lenient(text: str) -> Any:
    """json.loads with salvage for truncated model output."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # first complete object via raw_decode
    try:
        data, _ = json.JSONDecoder().raw_decode(text)
        return data
    except json.JSONDecodeError:
        pass
    # truncated {"items":[ {...}, {... incomplete
    m = re.search(r'"items"\s*:\s*\[', text)
    if m:
        items: List[dict] = []
        pos = m.end()
        dec = json.JSONDecoder()
        while pos < len(text):
            while pos < len(text) and text[pos] in " \t\n\r,":
                pos += 1
            if pos >= len(text) or text[pos] in "]}":
                break
            if text[pos] != "{":
                break
            try:
                obj, end = dec.raw_decode(text, pos)
            except json.JSONDecodeError:
                break
            if isinstance(obj, dict):
                items.append(obj)
            pos = end
        if items:
            return {"items": items}
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    raise ValueError(f"not JSON: {text[:200]!r}")


def parse_pcs_response(text: str) -> List[PCSItem]:
    """Parse model JSON into one or more PCSItem. Raises ValueError on failure."""
    text = (text or "").strip()
    if not text:
        raise ValueError("empty model response")

    # strip accidental fences
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    data = _loads_json_lenient(text)

    items: List[PCSItem] = []
    if isinstance(data, list):
        for el in data:
            it = _coerce_item(el)
            if it:
                items.append(it)
    elif isinstance(data, dict):
        if "items" in data and isinstance(data["items"], list):
            for el in data["items"]:
                it = _coerce_item(el)
                if it:
                    items.append(it)
        else:
            it = _coerce_item(data)
            if it:
                items.append(it)
    if not items:
        raise ValueError(f"no PCS fields in: {text[:300]!r}")
    return items[:5]


def read_transcript(path: str | Path, max_chars: int = 120_000) -> str:
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace").strip()
    if len(text) > max_chars:
        # head + tail so outro CTAs don't dominate mid content
        head = max_chars * 3 // 4
        tail = max_chars - head
        text = text[:head] + "\n\n[...truncated...]\n\n" + text[-tail:]
    return text


def extract_pcs_from_text(
    transcript: str,
    *,
    title: str = "",
    video_id: str = "",
    model: Optional[str] = None,
    host: Optional[str] = None,
    temperature: float = 0.2,
    timeout: float = 300.0,
) -> Tuple[List[PCSItem], str]:
    """Call Gemma; return (items, raw_response)."""
    prompt = USER_TEMPLATE.format(
        title=title or "(unknown)",
        video_id=video_id or "(unknown)",
        transcript=transcript or "(empty)",
    )
    raw = generate(
        prompt,
        model=model,
        host=host,
        system=SYSTEM_PROMPT,
        format_json=True,
        temperature=temperature,
        num_predict=1600,
        timeout=timeout,
    )
    items = parse_pcs_response(raw)
    return items, raw


def summarize_transcript_file(
    transcript_path: str | Path,
    *,
    channel: str = "",
    model: Optional[str] = None,
    host: Optional[str] = None,
    out_dir: Optional[str | Path] = None,
    force: bool = False,
) -> PCSRecord:
    """
    PCS for one transcript file. Writes `<video_id>.json` under out_dir
    (default: sibling `summaries/` next to `transcriptions/`).
    """
    path = Path(transcript_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)

    video_id = video_id_from_transcript_path(path) or path.stem[:11]
    title = title_from_transcript_path(path, video_id)

    if not channel:
        # .../channels/Drberg/transcriptions/foo.txt → Drberg
        parts = path.parts
        if "channels" in parts:
            i = parts.index("channels")
            if i + 1 < len(parts):
                channel = parts[i + 1]

    if out_dir is None:
        # prefer channels/<ch>/summaries
        if path.parent.name == "transcriptions":
            out_dir = path.parent.parent / "summaries"
        else:
            out_dir = path.parent / "summaries"
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{video_id}.json"

    if out_path.is_file() and not force:
        existing = json.loads(out_path.read_text(encoding="utf-8"))
        if existing.get("items"):
            items = [
                PCSItem(
                    problem=str(i.get("problem", "")),
                    cause=str(i.get("cause", "")),
                    solution=str(i.get("solution", "")),
                    symptoms=list(i.get("symptoms") or []),
                    related=list(i.get("related") or []),
                )
                for i in existing["items"]
            ]
        else:
            items = [
                PCSItem(
                    problem=str(existing.get("problem", "")),
                    cause=str(existing.get("cause", "")),
                    solution=str(existing.get("solution", "")),
                    symptoms=list(existing.get("symptoms") or []),
                    related=list(existing.get("related") or []),
                )
            ]
        return PCSRecord(
            video_id=existing.get("video_id", video_id),
            title=existing.get("title", title),
            channel=existing.get("channel", channel),
            source_transcript=existing.get("source_transcript", str(path)),
            model=existing.get("model", model or default_model()),
            created_at=existing.get("created_at", ""),
            items=items,
        )

    transcript = read_transcript(path)
    use_model = model or default_model()
    items, raw = extract_pcs_from_text(
        transcript,
        title=title,
        video_id=video_id,
        model=use_model,
        host=host,
    )
    record = PCSRecord(
        video_id=video_id,
        title=title,
        channel=channel or "unknown",
        source_transcript=str(path),
        model=use_model,
        created_at=datetime.now(timezone.utc).isoformat(),
        items=items,
        raw_response=raw,
    )
    out_path.write_text(
        json.dumps(record.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return record


def list_transcript_files(trans_dir: str | Path) -> List[Path]:
    d = Path(trans_dir)
    if not d.is_dir():
        return []
    return sorted(p for p in d.iterdir() if p.is_file() and p.suffix == ".txt")


def rebuild_index(summaries_dir: str | Path) -> Path:
    """Rewrite index.jsonl from all *.json PCS records (skip index itself)."""
    d = Path(summaries_dir)
    d.mkdir(parents=True, exist_ok=True)
    index_path = d / "index.jsonl"
    lines: List[str] = []
    for p in sorted(d.glob("*.json")):
        if p.name.startswith("_"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        # compact line for search
        row = {
            "video_id": data.get("video_id"),
            "title": data.get("title"),
            "problem": data.get("problem"),
            "cause": data.get("cause"),
            "solution": data.get("solution"),
            "symptoms": data.get("symptoms") or [],
            "related": data.get("related") or [],
            "items": data.get("items") or [],
            "model": data.get("model"),
            "created_at": data.get("created_at"),
        }
        lines.append(json.dumps(row, ensure_ascii=False))
    index_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return index_path


def search_index(
    summaries_dir: str | Path,
    query: str,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Naive case-insensitive substring search over index.jsonl (+ full json)."""
    d = Path(summaries_dir)
    index_path = d / "index.jsonl"
    q = query.lower().strip()
    if not q:
        return []
    hits: List[Dict[str, Any]] = []
    if index_path.is_file():
        for line in index_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            blob = json.dumps(row, ensure_ascii=False).lower()
            if q in blob:
                hits.append(row)
                if len(hits) >= limit:
                    break
    return hits


def batch_summarize_channel(
    channel_folder: str,
    *,
    channels_root: str = CHANNELS_ROOT,
    model: Optional[str] = None,
    host: Optional[str] = None,
    force: bool = False,
    limit: Optional[int] = None,
) -> List[PCSRecord]:
    """Process all transcripts under channels/<folder>/transcriptions/."""
    base = Path(channels_root) / channel_folder
    trans_dir = base / "transcriptions"
    out_dir = base / "summaries"
    files = list_transcript_files(trans_dir)
    if limit is not None:
        files = files[:limit]
    results: List[PCSRecord] = []
    for i, f in enumerate(files, 1):
        print(f"[{i}/{len(files)}] {f.name}", flush=True)
        try:
            rec = summarize_transcript_file(
                f,
                channel=channel_folder,
                model=model,
                host=host,
                out_dir=out_dir,
                force=force,
            )
            primary = rec.primary()
            rel = "; ".join(primary.related[:4]) if primary.related else "(none)"
            print(
                f"  → problem:  {primary.problem[:90]}\n"
                f"    cause:    {primary.cause[:90]}\n"
                f"    solution: {primary.solution[:90]}\n"
                f"    related:  {rel[:90]}",
                flush=True,
            )
            results.append(rec)
        except (OllamaError, ValueError, OSError) as e:
            print(f"  ERROR: {e}", file=sys.stderr, flush=True)
    rebuild_index(out_dir)
    print(f"Index: {out_dir / 'index.jsonl'} ({len(results)} ok)", flush=True)
    return results


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m suxxtext.pcs",
        description=(
            "Problem / Cause / Solution extraction via Ollama (Gemma). "
            "Fluff-free cards for symptom search (Dr. Berg style)."
        ),
    )
    p.add_argument(
        "--channel",
        help="Channel folder under channels/ (e.g. Drberg)",
    )
    p.add_argument(
        "--file",
        help="Single transcript .txt path",
    )
    p.add_argument(
        "--channels-root",
        default=CHANNELS_ROOT,
        help=f"Root for channel archives (default: {CHANNELS_ROOT})",
    )
    p.add_argument(
        "--model",
        default=None,
        help=f"Ollama model (default: env SUXXTEXT_OLLAMA_MODEL or {default_model()})",
    )
    p.add_argument(
        "--host",
        default=None,
        help=f"Ollama host (default: env OLLAMA_HOST or {ollama_host()})",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Re-summarize even if summary JSON exists",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max transcripts in channel batch",
    )
    p.add_argument(
        "--search",
        metavar="QUERY",
        help="Search existing summaries index for QUERY (requires --channel)",
    )
    p.add_argument(
        "--rebuild-index",
        action="store_true",
        help="Only rebuild index.jsonl for --channel",
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="Ping Ollama and list models, then exit",
    )
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    host = args.host
    model = args.model

    if args.check:
        h = host or ollama_host()
        ok = ping(h)
        print(f"Ollama at {h}: {'OK' if ok else 'UNREACHABLE'}")
        if ok:
            try:
                models = list_models(h)
                print("Models:", ", ".join(models) or "(none)")
            except OllamaError as e:
                print(f"list models failed: {e}", file=sys.stderr)
                return 1
            want = model or default_model()
            if want not in models and not any(m.startswith(want.split(":")[0]) for m in models):
                print(f"WARNING: preferred model {want!r} not in list", file=sys.stderr)
        return 0 if ok else 1

    if args.search:
        if not args.channel:
            print("--search requires --channel", file=sys.stderr)
            return 2
        sdir = Path(args.channels_root) / args.channel / "summaries"
        hits = search_index(sdir, args.search)
        if not hits:
            print(f"No hits for {args.search!r} in {sdir}")
            return 0
        for h in hits:
            print(
                f"- [{h.get('video_id')}] {h.get('title')}\n"
                f"  problem:  {h.get('problem')}\n"
                f"  cause:    {h.get('cause')}\n"
                f"  solution: {h.get('solution')}\n"
            )
        return 0

    if args.rebuild_index:
        if not args.channel:
            print("--rebuild-index requires --channel", file=sys.stderr)
            return 2
        sdir = Path(args.channels_root) / args.channel / "summaries"
        path = rebuild_index(sdir)
        print(f"Rebuilt {path}")
        return 0

    if not ping(host or ollama_host()):
        print(
            f"Ollama not reachable at {host or ollama_host()}. "
            "Start it (e.g. ollama serve) and retry.",
            file=sys.stderr,
        )
        return 1

    if args.file:
        rec = summarize_transcript_file(
            args.file,
            channel=args.channel or "",
            model=model,
            host=host,
            force=args.force,
        )
        # if channel given, also index
        if args.channel:
            sdir = Path(args.channels_root) / args.channel / "summaries"
            rebuild_index(sdir)
        print(json.dumps(rec.to_dict(), indent=2, ensure_ascii=False))
        return 0

    if args.channel:
        batch_summarize_channel(
            args.channel,
            channels_root=args.channels_root,
            model=model,
            host=host,
            force=args.force,
            limit=args.limit,
        )
        return 0

    build_parser().print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
