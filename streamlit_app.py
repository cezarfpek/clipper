import streamlit as st
import yt_dlp
import subprocess
import os
import tempfile
from pathlib import Path

def parse_time(time_str):
    """
    Converts a time string (hh:mm:ss, mm:ss, or ss) to total seconds (float).
    Example: "1:23" → 83 seconds, "2:30:45" → 9045 seconds.
    """
    parts = list(map(float, time_str.split(':')))
    if len(parts) == 1:
        return parts[0]
    elif len(parts) == 2:
        return parts[0] * 60 + parts[1]
    elif len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    else:
        raise ValueError(f"Invalid time format: {time_str}. Use hh:mm:ss, mm:ss, or ss.")

def download_and_resize_clip(url, start_time_str, end_time_str, cookies_content=None):
    """
    Downloads a YouTube clip and resizes it to 9:16 aspect ratio.
    
    Args:
        url (str): YouTube video URL.
        start_time_str (str): Start time in "hh:mm:ss", "mm:ss", or "ss" format.
        end_time_str (str): End time in the same format as start_time_str.
        cookies_content (str, optional): Content of cookies.txt file.
    
    Returns:
        str: Path to the processed video file.
    """
    # Convert time strings to seconds
    start_time = parse_time(start_time_str)
    end_time = parse_time(end_time_str)
    duration = end_time - start_time
    
    if duration <= 0:
        raise ValueError("End time must be after start time")
    
    # Create temporary directory for processing
    temp_dir = tempfile.mkdtemp()
    
    # Download the video and extract channel name
    temp_download = os.path.join(temp_dir, 'temp_download.%(ext)s')
    
    ydl_opts = {
        'format': 'best[ext=mp4]/best',  # Prefer single mp4 format to avoid merging
        'outtmpl': temp_download,
        'merge_output_format': 'mp4',
        'writeinfojson': False,
        'writesubtitles': False,
        'writeautomaticsub': False,
    }
    
    # Add cookies if provided
    if cookies_content:
        cookies_file = os.path.join(temp_dir, 'cookies.txt')
        with open(cookies_file, 'w') as f:
            f.write(cookies_content)
        ydl_opts['cookiefile'] = cookies_file
    
    # Extract video info to get channel name
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            channel_name = info.get('uploader', 'Unknown Channel')
            ydl.download([url])
        except Exception as e:
            raise Exception(f"Failed to download video: {str(e)}")
    
    # Find the downloaded file (it might have different extensions)
    downloaded_files = [f for f in os.listdir(temp_dir) if f.startswith('temp_download')]
    if not downloaded_files:
        raise Exception("No video file was downloaded")
    
    downloaded_file = os.path.join(temp_dir, downloaded_files[0])
    
    # Check if ffmpeg is available
    try:
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise Exception("FFmpeg is not available. Please check system dependencies.")
    
    # Trim the video first
    trimmed_file = os.path.join(temp_dir, 'trimmed.mp4')
    trim_cmd = [
        'ffmpeg',
        '-ss', str(start_time),
        '-i', downloaded_file,
        '-t', str(duration),
        '-c', 'copy',
        '-avoid_negative_ts', 'make_zero',
        '-y',
        trimmed_file
    ]
    
    try:
        subprocess.run(trim_cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise Exception(f"Failed to trim video: {e.stderr.decode() if e.stderr else str(e)}")
    
    # Resize to 9:16 aspect ratio
    resized_file = os.path.join(temp_dir, 'temp_resized.mp4')
    resize_cmd = [
        "ffmpeg",
        "-i", trimmed_file,
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
        "-c:a", "copy",
        "-preset", "fast",
        "-y",
        resized_file
    ]
    
    try:
        subprocess.run(resize_cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise Exception(f"Failed to resize video: {e.stderr.decode() if e.stderr else str(e)}")
    
    # Add credits overlay in the last second
    final_file = os.path.join(temp_dir, 'temp_final.mp4')
    
    # Clean the channel name and escape special characters for ffmpeg
    credits_text = f"credits: {channel_name} on Youtube"
    # Escape special characters for ffmpeg drawtext
    credits_text_escaped = credits_text.replace("'", r"\'").replace(":", r"\:")
    
    # Calculate when to show credits (last 1 second)
    credits_start = max(0, duration - 1)
    
    # Use a system font that should be available on most systems
    font_path = "DejaVu Sans"  # This should work on most Linux systems including Streamlit Cloud
    
    credits_cmd = [
        "ffmpeg",
        "-i", resized_file,
        "-vf", f"drawtext=text='{credits_text_escaped}':fontfile='{font_path}':fontsize=36:fontcolor=white:x=(w-text_w)/2:y=h*0.75:enable='between(t,{credits_start},{duration})'",
        "-c:a", "copy",
        "-preset", "fast",
        "-y",
        final_file
    ]
    
    try:
        subprocess.run(credits_cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        # If credits overlay fails, just use the resized video
        st.warning("Credits overlay failed, proceeding without credits")
        final_file = resized_file
    
    # Clean up intermediate files (but keep the final file)
    try:
        if os.path.exists(downloaded_file):
            os.remove(downloaded_file)
        if os.path.exists(trimmed_file) and trimmed_file != final_file:
            os.remove(trimmed_file)
        if os.path.exists(resized_file) and resized_file != final_file:
            os.remove(resized_file)
    except Exception:
        pass  # Ignore cleanup errors
    
    return final_file

def main():
    st.set_page_config(
        page_title="YouTube Clip Downloader",
        page_icon="🎬",
        layout="wide"
    )
    
    st.title("🎬 YouTube Clip Downloader & Resizer")
    st.markdown("Download YouTube clips and automatically resize them to 9:16 aspect ratio (1080x1920)")
    
    # Create form
    with st.form("clip_downloader_form"):
        st.subheader("Video Details")
        
        # URL input
        url = st.text_input(
            "YouTube URL",
            placeholder="https://www.youtube.com/watch?v=...",
            help="Enter the full YouTube video URL"
        )
        
        # Time inputs
        col1, col2 = st.columns(2)
        with col1:
            start_time = st.text_input(
                "Start Time",
                placeholder="1:30 or 1:30:45",
                help="Format: ss, mm:ss, or hh:mm:ss"
            )
        
        with col2:
            end_time = st.text_input(
                "End Time",
                placeholder="2:15 or 2:15:30",
                help="Format: ss, mm:ss, or hh:mm:ss"
            )
        
        # Cookie content input
        st.subheader("Optional: Browser Cookies")
        cookies_content = st.text_area(
            "Paste cookies.txt content",
            height=100,
            placeholder="# Netscape HTTP Cookie File\n# This is a generated file! Do not edit.\n\n.youtube.com\tTRUE\t/\tFALSE\t...",
            help="Paste the content of your cookies.txt file if the video requires authentication"
        )
        
        # Submit button
        submitted = st.form_submit_button("Download & Process Clip", type="primary")
    
    # Process the form submission
    if submitted:
        if not url:
            st.error("Please enter a YouTube URL")
            return
        
        if not start_time or not end_time:
            st.error("Please enter both start and end times")
            return
        
        try:
            # Validate time formats
            parse_time(start_time)
            parse_time(end_time)
        except ValueError as e:
            st.error(f"Invalid time format: {e}")
            return
        
        try:
            with st.spinner("Downloading and processing video... This may take a few minutes."):
                # Download and process the clip
                processed_video_path = download_and_resize_clip(
                    url, start_time, end_time, cookies_content.strip() if cookies_content else None
                )
                
                st.success("✅ Video processed successfully!")
                
                # Display video info
                st.subheader("Processed Video")
                
                # Show video player in a much smaller, centered column
                col1, col2, col3 = st.columns([2, 1, 2])
                with col2:
                    with open(processed_video_path, 'rb') as video_file:
                        video_bytes = video_file.read()
                        st.video(video_bytes)
                
                # Download button
                filename = f"clip_{start_time.replace(':', '-')}_to_{end_time.replace(':', '-')}.mp4"
                st.download_button(
                    label="📥 Download Processed Video",
                    data=video_bytes,
                    file_name=filename,
                    mime="video/mp4"
                )
                
                # Video details
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Resolution", "1080x1920")
                with col2:
                    st.metric("Aspect Ratio", "9:16")
                with col3:
                    duration_seconds = parse_time(end_time) - parse_time(start_time)
                    st.metric("Duration", f"{duration_seconds:.1f}s")
        
        except Exception as e:
            st.error(f"❌ Error processing video: {str(e)}")
            st.error("Please check your URL, time formats, and try again.")
    
    # Instructions
    with st.expander("ℹ️ Instructions & Tips"):
        st.markdown("""
        ### How to use:
        1. **YouTube URL**: Paste the full YouTube video URL
        2. **Start/End Time**: Use formats like:
           - `90` (90 seconds)
           - `1:30` (1 minute 30 seconds)
           - `2:15:45` (2 hours 15 minutes 45 seconds)
        3. **Cookies (Optional)**: Paste cookies.txt content if the video requires login
        
        ### Getting cookies.txt:
        - Use browser extensions like "Get cookies.txt" for Chrome/Firefox
        - Export cookies from the YouTube domain and copy the content
        - This is needed for private/age-restricted videos
        
        ### Output:
        - Video will be automatically resized to 9:16 aspect ratio (1080x1920)
        - Perfect for mobile/vertical video platforms
        - Download the processed video using the download button
        """)

if __name__ == "__main__":
    main()
