import json
import os
import datetime
from collections import Counter
import html
import glob # Added glob
import os # Ensure os is imported as it's used by new functions
import sys # Import sys for sys.exit()
import colorama # Import colorama for colored output
from transcribe2 import sanitize_filename # Import sanitize_filename

colorama.init(autoreset=True) # Initialize colorama

# --- Configuration ---
# JSON_FILE_PATH = 'channels/NowYouKnowChannel/NowYouKnowChannel-full-history.json' # Removed
OUTPUT_DIR = 'report-generator-css'
HTML_FILE_PATH = os.path.join(OUTPUT_DIR, 'youtube_stats_report.html')
CSS_FILE_PATH = os.path.join(OUTPUT_DIR, 'css', 'style.css')
JS_FILE_PATH = os.path.join(OUTPUT_DIR, 'js', 'script.js')

# --- Helper Functions ---
def ensure_dir(directory):
    """Ensures that a directory exists, creating it if necessary."""
    os.makedirs(directory, exist_ok=True)

def format_number(num):
    """Formats a number with commas as thousands separators."""
    return f"{num:,}" if isinstance(num, (int, float)) else num

def get_video_id(video_data):
    """Extracts video ID, trying common key patterns."""
    if 'id' in video_data and isinstance(video_data['id'], str):
        return video_data['id']
    if 'id' in video_data and isinstance(video_data['id'], dict) and 'videoId' in video_data['id']:
        return video_data['id']['videoId']
    if 'contentDetails' in video_data and 'videoId' in video_data['contentDetails']:
        return video_data['contentDetails']['videoId']
    if 'resourceId' in video_data and 'videoId' in video_data['resourceId']: # Common in playlistItems
        return video_data['resourceId']['videoId']
    return None

def get_video_title(video_data):
    title = "N/A"
    if 'snippet' in video_data and 'title' in video_data['snippet']:
        title = video_data['snippet']['title']
    elif 'title' in video_data:
        title = video_data['title']
    return html.escape(title)

def get_video_thumbnail(video_data):
    # Per user request, thumbnails are not important, always return placeholder
    return "https://via.placeholder.com/120x90.png?text=No+Video+Thumbnail"

def get_stat(data, path, default=0):
    """Safely get a nested value from a dictionary."""
    keys = path.split('.')
    current = data
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list) and key.isdigit() and int(key) < len(current):
            current = current[int(key)]
        else:
            return default
    try:
        return int(current) if isinstance(current, (str, int, float)) and str(current).isdigit() else (current if current else default)
    except (ValueError, TypeError):
        return default


def parse_iso_duration(duration_str):
    """Parses ISO 8601 duration string (e.g., PT1M30S) into seconds."""
    if not duration_str or not duration_str.startswith('PT'):
        return 0
    duration_str = duration_str[2:]
    seconds = 0
    number_buffer = ""
    for char in duration_str:
        if char.isdigit():
            number_buffer += char
        elif char == 'H':
            seconds += int(number_buffer) * 3600
            number_buffer = ""
        elif char == 'M':
            seconds += int(number_buffer) * 60
            number_buffer = ""
        elif char == 'S':
            seconds += int(number_buffer)
            number_buffer = ""
    return seconds

def format_duration(seconds):
    """Formats seconds into HH:MM:SS or MM:SS string."""
    if not isinstance(seconds, (int, float)) or seconds < 0:
        return "N/A"
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    if hours > 0:
        return f"{hours:02}:{minutes:02}:{secs:02}"
    return f"{minutes:02}:{secs:02}"

def get_upload_date(video_data):
    date_str = None
    if 'snippet' in video_data and 'publishedAt' in video_data['snippet']:
        date_str = video_data['snippet']['publishedAt']
    elif 'contentDetails' in video_data and 'videoPublishedAt' in video_data['contentDetails']: # For playlistItems
        date_str = video_data['contentDetails']['videoPublishedAt']
    
    if date_str:
        try:
            return datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00')).strftime('%Y-%m-%d')
        except ValueError:
            return "N/A"
    return "N/A"

def discover_and_select_json_file(base_dir='channels'):
    """Discovers JSON files matching '*-full-history.json' and allows user selection."""
    # Construct the search pattern for recursive search in subdirectories
    search_pattern = os.path.join(base_dir, '**', '*-full-history.json')
    
    absolute_base_dir = os.path.abspath(base_dir)
    print(f"Searching for '*-full-history.json' files in '{absolute_base_dir}' and its subdirectories...")
    
    found_files = glob.glob(search_pattern, recursive=True)

    if not found_files:
        print(f"No '*-full-history.json' files found in the '{base_dir}' directory or its subdirectories.")
        return None

    if len(found_files) == 1:
        print(f"Automatically selected the only file found: {found_files[0]}")
        return found_files[0]

    print("\nMultiple '*-full-history.json' files found.")
    print(f"{colorama.Fore.GREEN}Please select a channel to generate statistics for.{colorama.Style.RESET_ALL}")
    # Display files in a numbered list with bold white channel names.
    for i, file_path in enumerate(found_files):
        # Extract the channel folder name
        parts = file_path.split(os.sep)
        channel_folder_name = parts[-2] # e.g., 'Buggs' from 'channels/Buggs/Buggs-full-history.json'
        
        # Reconstruct the path with formatting
        formatted_path = os.path.join(*parts[:-2], f"{colorama.Fore.WHITE + colorama.Style.BRIGHT}{channel_folder_name}{colorama.Style.RESET_ALL}", parts[-1])
        
        print(f"  {i + 1}: {formatted_path}")
    print(f"{colorama.Fore.WHITE + colorama.Style.BRIGHT}M. Go back to main menu{colorama.Style.RESET_ALL}") # Added option to go back
    print() 

    while True:
        try:
            selection = input(f"Enter number (1-{len(found_files)}) or M: ").strip().lower()
            if selection == 'm':
                print("Returning to main menu.")
                return None # Signal to go back to main menu
            
            selected_index = int(selection) - 1
            if 0 <= selected_index < len(found_files):
                selected_file = found_files[selected_index]
                print(f"You selected: {selected_file}")
                return selected_file
            else:
                print(f"Invalid selection. Please enter a number between 1 and {len(found_files)} or 'M'.")
        except ValueError:
            print("Invalid input. Please enter a number or 'M'.")
        except (EOFError, KeyboardInterrupt): 
            print("\nSelection aborted by user.")
            return None

# --- Data Loading and Processing ---
def load_youtube_data(file_path):
    """Loads YouTube data from the JSON file.
    Returns a tuple: (list_of_video_items, channel_information_dict)
    """
    print(f"Attempting to load data from: {file_path}")
    video_items = []
    channel_info = {}
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

            if isinstance(data, dict):
                # Extract channel-level information if present
                # Common keys for channel info, adjust as per your JSON structure
                for key in ['channel_id', 'channel_name', 'channel_url', 'channel_follower_count', 'description', 'channel_banner_url', 'channel_thumbnail_url']:
                    if key in data:
                        channel_info[key] = data[key]
                
                # Try to find video items, prioritizing "entries"
                if 'entries' in data and isinstance(data['entries'], list):
                    video_items = data['entries']
                    print(f"Found 'entries' key with a list of {len(video_items)} video items.")
                elif 'items' in data and isinstance(data['items'], list):
                    video_items = data['items']
                    print(f"Found 'items' key with a list of {len(video_items)} video items.")
                elif 'videos' in data and isinstance(data['videos'], list):
                    video_items = data['videos']
                    print(f"Found 'videos' key with a list of {len(video_items)} video items.")
                else:
                    # If the dict itself might be a single video item (less common for "full-history" files)
                    if 'id' in data and ('title' in data or 'description' in data): # Check for common video fields
                         video_items = [data]
                         print("Warning: Loaded a dictionary that looks like a single video item. Processing as such.")
                    else:
                        print("Warning: Loaded a dictionary, but couldn't find a clear list of videos under 'entries', 'items', or 'videos' keys. No video items extracted from dict.")
            elif isinstance(data, list):
                video_items = data # Assume it's a direct list of video objects
                print(f"Loaded a list of {len(video_items)} elements directly. No separate channel info extracted from top level.")
            else:
                print(f"Warning: Unexpected data type loaded: {type(data)}. Attempting to process as empty.")
                
    except FileNotFoundError:
        print(f"Error: File not found at {file_path}")
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {file_path}")
    except Exception as e:
        print(f"An unexpected error occurred while loading data: {e}")
    
    return video_items, channel_info

def process_videos_data(videos_raw_data):
    """Processes raw video data to extract key statistics."""
    processed_videos = []
    if not videos_raw_data or not isinstance(videos_raw_data, list):
        print("No valid video data to process.")
        return processed_videos

    for video_item in videos_raw_data:
        if not isinstance(video_item, dict):
            # print(f"Skipping non-dict item: {video_item}")
            continue

        # Adapt to common YouTube API structures (e.g., video resource, search result, playlist item)
        # Based on example.json, fields are directly under video_item for 'entries'
        
        video_id = video_item.get('id')
        if not video_id: 
            # print(f"Skipping item due to missing video ID: {str(video_item)[:100]}...")
            continue

        title = html.escape(video_item.get('title', 'N/A'))
        
        # View count: prioritize 'view_count', fallback to 'concurrent_view_count' if 'view_count' is None
        raw_view_count = video_item.get('view_count')
        if raw_view_count is None: # Specifically check for None, as 0 is a valid view count
            raw_view_count = video_item.get('concurrent_view_count') # Fallback for live videos
        
        view_count = 0
        if raw_view_count is not None:
            try:
                view_count = int(raw_view_count)
            except (ValueError, TypeError):
                view_count = 0 # Default to 0 if conversion fails

        # Like count, comment count are missing in the sample, will default to 0
        like_count = int(video_item.get('like_count', 0) or 0) # Ensure None becomes 0
        comment_count = int(video_item.get('comment_count', 0) or 0) # Ensure None becomes 0
        dislike_count = 0 # Not available

        # Duration is directly in seconds in the sample
        duration_seconds = 0
        raw_duration = video_item.get('duration')
        if raw_duration is not None:
            try:
                duration_seconds = float(raw_duration) # Duration can be float
            except (ValueError, TypeError):
                duration_seconds = 0
        
        # Upload date is missing in sample entries, get_upload_date will return "N/A"
        upload_date = get_upload_date(video_item) 
        thumbnail_url = get_video_thumbnail(video_item)

        processed_videos.append({
            'id': video_id,
            'title': title,
            'upload_date': upload_date, # Will be "N/A"
            'view_count': view_count,
            'like_count': like_count,   # Will be 0
            'dislike_count': dislike_count, 
            'comment_count': comment_count, # Will be 0
            'duration_seconds': duration_seconds, 
            'duration_formatted': format_duration(duration_seconds),
            'thumbnail_url': thumbnail_url,
            'url': f"https://www.youtube.com/watch?v={video_id}"
        })
    
    # Sort videos by upload date (newest first) if dates are valid
    try:
        processed_videos.sort(key=lambda v: datetime.datetime.strptime(v['upload_date'], '%Y-%m-%d') if v['upload_date'] != "N/A" else datetime.datetime.min, reverse=True)
    except ValueError:
        print("Warning: Could not sort videos by date due to inconsistent date formats.")

    return processed_videos

# --- Statistics Calculation ---
def calculate_overall_stats(videos, channel_info=None): # Added channel_info parameter
    if not videos:
        return {
            'total_videos': 0, 'total_views': 0, 'total_likes': 0,
            'total_comments': 0, 'total_duration_seconds': 0,
            'average_views_per_video': 0, 'average_likes_per_video': 0,
            'average_comments_per_video': 0, 'average_duration_seconds': 0,
            'most_recent_upload_date': "N/A", 'oldest_upload_date': "N/A"
        }

    total_videos = len(videos)
    total_views = sum(v['view_count'] for v in videos)
    total_likes = sum(v['like_count'] for v in videos)
    total_comments = sum(v['comment_count'] for v in videos)
    total_duration_seconds = sum(v['duration_seconds'] for v in videos)

    average_views_per_video = total_views / total_videos if total_videos > 0 else 0
    average_likes_per_video = total_likes / total_videos if total_videos > 0 else 0
    average_comments_per_video = total_comments / total_videos if total_videos > 0 else 0
    average_duration_seconds = total_duration_seconds / total_videos if total_videos > 0 else 0
    
    valid_dates = [datetime.datetime.strptime(v['upload_date'], '%Y-%m-%d') for v in videos if v['upload_date'] != "N/A"]
    most_recent_upload_date = max(valid_dates).strftime('%Y-%m-%d') if valid_dates else "N/A"
    oldest_upload_date = min(valid_dates).strftime('%Y-%m-%d') if valid_dates else "N/A"


    return {
        'total_videos': total_videos,
        'total_views': total_views,
        'total_likes': total_likes,
        'total_comments': total_comments,
        'total_duration_seconds': total_duration_seconds,
        'average_views_per_video': round(average_views_per_video),
        'average_likes_per_video': round(average_likes_per_video),
        'average_comments_per_video': round(average_comments_per_video),
        'average_duration_seconds': round(average_duration_seconds),
        'most_recent_upload_date': most_recent_upload_date,
        'oldest_upload_date': oldest_upload_date
    }

def get_top_videos(videos, key, n=10):
    return sorted([v for v in videos if isinstance(v.get(key), (int, float))], key=lambda v: v.get(key, 0), reverse=True)[:n]

def get_views_over_time(videos):
    views_by_month = Counter()
    if not videos: return {}
    for video in videos:
        if video['upload_date'] != "N/A":
            try:
                date_obj = datetime.datetime.strptime(video['upload_date'], '%Y-%m-%d')
                month_year = date_obj.strftime('%Y-%m')
                views_by_month[month_year] += video['view_count']
            except ValueError:
                continue # Skip if date format is wrong
    
    sorted_months = sorted(views_by_month.keys())
    return {
        "labels": sorted_months,
        "data": [views_by_month[month] for month in sorted_months]
    }

def get_uploads_over_time(videos):
    uploads_by_month = Counter()
    if not videos: return {}
    for video in videos:
        if video['upload_date'] != "N/A":
            try:
                date_obj = datetime.datetime.strptime(video['upload_date'], '%Y-%m-%d')
                month_year = date_obj.strftime('%Y-%m')
                uploads_by_month[month_year] += 1
            except ValueError:
                continue
    
    sorted_months = sorted(uploads_by_month.keys())
    return {
        "labels": sorted_months,
        "data": [uploads_by_month[month] for month in sorted_months]
    }


# --- HTML Generation ---
def generate_html_report(videos, overall_stats, channel_info, views_over_time_data, uploads_over_time_data, top_videos_by_views, top_videos_by_likes, top_videos_by_comments, top_videos_by_duration):
    channel_name = channel_info.get('channel_name_for_report', "Channel Statistics") if channel_info else "Channel Statistics"
    
    # Prepare data for JavaScript
    # Limit the number of videos passed to JS for performance if the list is huge
    js_videos_data = json.dumps([{'title': v['title'], 'upload_date': v['upload_date'], 'view_count': v['view_count'], 'like_count': v['like_count'], 'comment_count': v['comment_count'], 'duration_formatted': v['duration_formatted'], 'url': v['url'], 'thumbnail_url': v['thumbnail_url'] } for v in videos[:500]]) # Pass limited data for table
    # Prepare data for JavaScript
    # Limit the number of videos passed to JS for performance if the list is huge
    js_videos_data = json.dumps([{'title': v['title'], 'upload_date': v['upload_date'], 'view_count': v['view_count'], 'like_count': v['like_count'], 'comment_count': v['comment_count'], 'duration_formatted': v['duration_formatted'], 'url': v['url'], 'thumbnail_url': v['thumbnail_url'] } for v in videos[:500]]) # Pass limited data for table
    # Views and Uploads over time data will be empty due to missing upload dates, but keep structure
    js_views_over_time_data = json.dumps(views_over_time_data)
    js_uploads_over_time_data = json.dumps(uploads_over_time_data)
    
    # Data for new charts
    js_top_videos_by_views_data = json.dumps([{'title': v['title'], 'view_count': v['view_count']} for v in top_videos_by_views])
    js_top_videos_by_duration_data = json.dumps([{'title': v['title'], 'duration_formatted': v['duration_formatted'], 'duration_seconds': v['duration_seconds']} for v in top_videos_by_duration])
    js_top_videos_by_likes_data = json.dumps([{'title': v['title'], 'like_count': v['like_count']} for v in top_videos_by_likes])


    html_content = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(channel_name)} Statistics Report</title>
    <link rel="stylesheet" href="../../report-generator-css/css/style.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/5.15.4/css/all.min.css">
</head>
<body>
    <header>
        <h1><i class="fab fa-youtube"></i> <a href="{channel_info.get('channel_url', '#')}" target="_blank">{html.escape(channel_name)} Statistics Report</a></h1>
    </header>
    <main>
        <section id="overall-summary">
            <h2><i class="fas fa-chart-pie"></i> Overall Summary</h2>
            <div class="summary-grid">
                <div class="summary-card"><h3><i class="fas fa-video"></i> Total Videos</h3><p>{format_number(overall_stats['total_videos'])}</p></div>
                <div class="summary-card"><h3><i class="fas fa-eye"></i> Total Views</h3><p>{format_number(overall_stats['total_views'])}</p></div>
                <div class="summary-card"><h3><i class="fas fa-thumbs-up"></i> Total Likes</h3><p>{format_number(overall_stats['total_likes'])}</p></div>
                <div class="summary-card"><h3><i class="fas fa-comments"></i> Total Comments</h3><p>{format_number(overall_stats['total_comments'])}</p></div>
                <div class="summary-card"><h3><i class="fas fa-clock"></i> Total Duration</h3><p>{format_duration(overall_stats['total_duration_seconds'])}</p></div>
                <div class="summary-card"><h3><i class="fas fa-binoculars"></i> Avg Views/Video</h3><p>{format_number(overall_stats['average_views_per_video'])}</p></div>
                <div class="summary-card"><h3><i class="fas fa-heart"></i> Avg Likes/Video</h3><p>{format_number(overall_stats['average_likes_per_video'])}</p></div>
                <div class="summary-card"><h3><i class="fas fa-comment-dots"></i> Avg Comments/Video</h3><p>{format_number(overall_stats['average_comments_per_video'])}</p></div>
                <div class="summary-card"><h3><i class="fas fa-hourglass-half"></i> Avg Duration/Video</h3><p>{format_duration(overall_stats['average_duration_seconds'])}</p></div>
                <div class="summary-card"><h3><i class="fas fa-calendar-alt"></i> Oldest Upload</h3><p>{overall_stats['oldest_upload_date']}</p></div>
                <div class="summary-card"><h3><i class="fas fa-calendar-check"></i> Newest Upload</h3><p>{overall_stats['most_recent_upload_date']}</p></div>
            </div>
        </section>

        <section id="charts">
            <h2><i class="fas fa-chart-line"></i> Statistics</h2>
            <div class="chart-grid">
                <div class="chart-container"><canvas id="topVideosByViewsChart"></canvas></div>
                <div class="chart-container"><canvas id="topVideosByDurationChart"></canvas></div>
                <div class="chart-container"><canvas id="topVideosByLikesChart"></canvas></div>
            </div>
        </section>
        
        <section id="video-details">
            <h2><i class="fas fa-list-ul"></i> Video Details</h2>
            <input type="text" id="videoSearchInput" onkeyup="filterVideoTable()" placeholder="Search for videos by title...">
            <table id="videosTable">
                <thead>
                    <tr>
                        <th onclick="sortTable(0, 'videosTable')">Thumbnail</th>
                        <th onclick="sortTable(1, 'videosTable')">Title</th>
                        <th onclick="sortTable(2, 'videosTable', true)">Upload Date <i class="fas fa-sort"></i></th>
                        <th onclick="sortTable(3, 'videosTable', true)">Views <i class="fas fa-sort"></i></th>
                        <th onclick="sortTable(4, 'videosTable', true)">Likes <i class="fas fa-sort"></i></th>
                        <th onclick="sortTable(5, 'videosTable', true)">Comments <i class="fas fa-sort"></i></th>
                        <th onclick="sortTable(6, 'videosTable', true)">Duration <i class="fas fa-sort"></i></th>
                    </tr>
                </thead>
                <tbody>
                    {"".join([f'''<tr>
                        <td><a href="{v['url']}" target="_blank"><img src="{v['thumbnail_url']}" alt="Thumbnail" class="video-thumbnail"></a></td>
                        <td><a href="{v['url']}" target="_blank">{v['title']}</a></td>
                        <td>{v['upload_date']}</td>
                        <td>{format_number(v['view_count'])}</td>
                        <td>{format_number(v['like_count'])}</td>
                        <td>{format_number(v['comment_count'])}</td>
                        <td>{v['duration_formatted']}</td>
                    </tr>''' for v in videos])}
                </tbody>
            </table>
        </section>
    </main>
    <footer>
        <p>Report generated on {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </footer>

    <script id="videoData" type="application/json">{js_videos_data}</script>
    <script id="viewsOverTimeData" type="application/json">{js_views_over_time_data}</script>
    <script id="uploadsOverTimeData" type="application/json">{js_uploads_over_time_data}</script>
    <script id="topVideosByViewsData" type="application/json">{js_top_videos_by_views_data}</script>
    <script id="topVideosByDurationData" type="application/json">{js_top_videos_by_duration_data}</script>
    <script id="topVideosByLikesData" type="application/json">{js_top_videos_by_likes_data}</script>
    <script src="../../report-generator-css/js/script.js"></script>
</body>
</html>
    """
    return html_content

# --- Main Execution ---
if __name__ == "__main__":
    print("Starting YouTube Channel statistics generator.")
    # Ensure output directories exist (general output, css, js)
    ensure_dir(OUTPUT_DIR)
    ensure_dir(os.path.join(OUTPUT_DIR, 'css')) # General CSS folder
    ensure_dir(os.path.join(OUTPUT_DIR, 'js'))  # General JS folder

    selected_json_path = discover_and_select_json_file()

    if selected_json_path is None: # If user chose to go back to main menu
        sys.exit(0) # Exit yt_channel_analyzer.py, returning control to transcribe2.py

    if selected_json_path:
        raw_video_entries, channel_info = load_youtube_data(selected_json_path)
        
        # Determine channel name for report and directory
        # Sanitize channel name for use in file/directory names
        raw_channel_name = channel_info.get('channel_name')
        if not raw_channel_name:
            try:
                raw_channel_name = os.path.basename(os.path.dirname(selected_json_path))
                if not raw_channel_name or raw_channel_name == "." or raw_channel_name == "channels": # if dirname gives current dir or top 'channels'
                    raw_channel_name = os.path.splitext(os.path.basename(selected_json_path))[0].replace('-full-history', '')

            except Exception:
                raw_channel_name = "UnknownChannel"
        
        # Sanitize the channel name for filesystem using the imported function
        sanitized_channel_name = sanitize_filename(raw_channel_name)

        # Update channel_info with this potentially derived/sanitized name
        channel_info['channel_name_for_report'] = raw_channel_name # Keep original for display
        channel_info['sanitized_channel_name'] = sanitized_channel_name # For file paths

        # Create channel-specific output directory within 'channels'
        channel_output_dir = os.path.join('channels', sanitized_channel_name)
        ensure_dir(channel_output_dir)
        
        # Define channel-specific HTML file path
        channel_html_file_name = f"{sanitized_channel_name}_statistics.html"
        channel_html_file_path = os.path.join(channel_output_dir, channel_html_file_name)


        if not raw_video_entries and not channel_info.get('channel_id') and not channel_info.get('channel_name_for_report'):
            print(f"No video data loaded and minimal channel info found from {selected_json_path}. Exiting.")
        else:
            print(f"Processing data for channel: {channel_info.get('channel_name_for_report', 'N/A')}")
            if 'channel_follower_count' in channel_info:
                 print(f"Followers: {channel_info.get('channel_follower_count', 'N/A')}")

            videos = process_videos_data(raw_video_entries)
            
            if not videos and not raw_video_entries:
                print("No videos found in the JSON to process. HTML report will be very limited.")
            elif not videos and raw_video_entries: 
                print("No videos could be successfully processed from the entries. HTML report may be limited.")

            overall_stats = calculate_overall_stats(videos, channel_info)
            
            views_over_time_data = get_views_over_time(videos)
            uploads_over_time_data = get_uploads_over_time(videos)
            top_videos_by_views = get_top_videos(videos, 'view_count', n=10)
            top_videos_by_duration = get_top_videos(videos, 'duration_seconds', n=10) # New: Top videos by duration
            top_videos_by_likes = get_top_videos(videos, 'like_count', n=10) 
            top_videos_by_comments = get_top_videos(videos, 'comment_count', n=10)

            # Pass channel_info (which now includes 'channel_name_for_report') and new top video lists
            html_report = generate_html_report(videos, overall_stats, channel_info, views_over_time_data, uploads_over_time_data, top_videos_by_views, top_videos_by_likes, top_videos_by_comments, top_videos_by_duration)
            
            try:
                with open(channel_html_file_path, 'w', encoding='utf-8') as f:
                    f.write(html_report)
                print(f"HTML report generated successfully at {channel_html_file_path}")
            except IOError as e:
                print(f"Error writing HTML file: {e}")
    else:
        print("No JSON file selected. Exiting.")


    # CSS and JS files are general, not channel-specific in this setup
    # If they were meant to be channel-specific, their paths would need adjustment too.
    # For now, they remain in output/css and output/js
    css_file_to_ensure = os.path.join(OUTPUT_DIR, 'css', 'style.css')
    js_file_to_ensure = os.path.join(OUTPUT_DIR, 'js', 'script.js')

    if not os.path.exists(css_file_to_ensure):
        with open(css_file_to_ensure, 'w', encoding='utf-8') as f:
            f.write("/* CSS styles will go here */\nbody { font-family: sans-serif; margin: 0; background-color: #f4f4f4; color: #333; }\nheader { background-color: #333; color: white; padding: 1em 0; text-align: center; }\nmain { padding: 1em; }\n.summary-grid, .chart-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 1em; margin-bottom: 2em; }\n.summary-card, .chart-container { background-color: white; padding: 1em; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }\n h2 { border-bottom: 2px solid #eee; padding-bottom: 0.5em; }")
        print(f"Created placeholder CSS file: {css_file_to_ensure}")

    if not os.path.exists(js_file_to_ensure):
        with open(js_file_to_ensure, 'w', encoding='utf-8') as f:
            f.write("// JavaScript for charts and interactivity will go here\nconsole.log('Script loaded');")
        print(f"Created placeholder JS file: {js_file_to_ensure}")
        
    print("YouTube Channel Analyzer finished.")
