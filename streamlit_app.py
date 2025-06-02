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

def download_and_resize_clip(url, start_time_str, end_time_str, cookies_content=None, progress_bar=None, status_text=None):
    """
    Downloads a YouTube clip and resizes it to 9:16 aspect ratio.
    
    Args:
        url (str): YouTube video URL.
        start_time_str (str): Start time in "hh:mm:ss", "mm:ss", or "ss" format.
        end_time_str (str): End time in the same format as start_time_str.
        cookies_content (str, optional): Content of cookies.txt file.
        progress_bar (streamlit.delta_generator.DeltaGenerator, optional): Streamlit progress bar element.
        status_text (streamlit.delta_generator.DeltaGenerator, optional): Streamlit text element for status.
    
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
    
    def my_hook(d):
        if progress_bar and status_text:
            if d['status'] == 'downloading':
                percent_str = d.get('_percent_str', '0.0%')
                speed_str = d.get('_speed_str', 'N/A')
                eta_str = d.get('_eta_str', 'N/A')
                try:
                    cleaned_percent_str = percent_str.strip('%')
                    p = float(cleaned_percent_str) / 100.0
                    progress_bar.progress(p)
                except ValueError:
                    progress_bar.progress(0)
                
                status_text.text(f"Downloading: {percent_str} at {speed_str} (ETA: {eta_str})")
            elif d['status'] == 'finished':
                progress_bar.progress(1.0)
                status_text.text("Download complete. Initializing processing...")
            elif d['status'] == 'error':
                status_text.text("Error during download.")

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]/bestvideo/best[ext=mp4]/best',
        'outtmpl': temp_download,
        'writeinfojson': False,
        'writesubtitles': False,    
        'writeautomaticsub': False,
        'progress_hooks': [my_hook],
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
            if status_text: status_text.text("Extracting video information...")
            info = ydl.extract_info(url, download=False)
            channel_name = info.get('uploader', 'Unknown Channel')
            if status_text: status_text.text("Starting download...")
            ydl.download([url])
        except Exception as e:
            raise Exception(f"Failed to download video: {str(e)}")
    
    # Find the downloaded file (it might have different extensions)
    downloaded_files = [f for f in os.listdir(temp_dir) if f.startswith('temp_download')]
    if not downloaded_files:
        raise Exception("No video file was downloaded")
    
    downloaded_file = os.path.join(temp_dir, downloaded_files[0])
    
    if status_text: status_text.text("Checking FFmpeg...")
    # Check if ffmpeg is available and find its path
    ffmpeg_path = 'ffmpeg'
    try:
        subprocess.run([ffmpeg_path, '-version'], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        try:
            ffmpeg_path = '/usr/bin/ffmpeg'
            subprocess.run([ffmpeg_path, '-version'], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise Exception("FFmpeg is not available. Please check system dependencies.")
    
    # Trim the video first
    if status_text: status_text.text("Trimming video...")
    trimmed_file = os.path.join(temp_dir, 'trimmed.mp4')
    trim_cmd = [
        ffmpeg_path,
        '-ss', str(start_time),
        '-i', downloaded_file,
        '-t', str(duration),
        '-c:v', 'copy',
        '-an',
        '-avoid_negative_ts', 'make_zero',
        '-y',
        trimmed_file
    ]
    
    try:
        result = subprocess.run(trim_cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        if status_text: status_text.text(f"Error trimming video: {e.stderr if e.stderr else str(e)}")
        raise Exception(f"Failed to trim video: {e.stderr if e.stderr else str(e)}")
    
    # Resize to 9:16 aspect ratio
    if status_text: status_text.text("Resizing video...")
    resized_file = os.path.join(temp_dir, 'temp_resized.mp4')
    resize_cmd = [
        ffmpeg_path,
        "-i", trimmed_file,
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
        "-an",
        "-preset", "fast",
        "-y",
        resized_file
    ]
    
    try:
        result = subprocess.run(resize_cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        if status_text: status_text.text(f"Error resizing video: {e.stderr if e.stderr else str(e)}")
        raise Exception(f"Failed to resize video: {e.stderr if e.stderr else str(e)}")
    
    # Add credits overlay in the last second
    if status_text: status_text.text("Adding credits...")
    final_file = os.path.join(temp_dir, 'temp_final.mp4')
    
    credits_text = f"credits: {channel_name} on Youtube"
    credits_text_escaped = credits_text.replace("'", r"\'").replace(":", r"\:")
    credits_start = max(0, duration - 1)
    
    credits_cmd = [
        ffmpeg_path,
        "-i", resized_file,
        "-vf", f"drawtext=text='{credits_text_escaped}':fontsize=36:fontcolor=white:x=(w-text_w)/2:y=h*0.75:enable='between(t,{credits_start},{duration})'",
        "-an",
        "-preset", "fast",
        "-y",
        final_file
    ]
    
    try:
        result = subprocess.run(credits_cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        if status_text: status_text.text("Credits overlay failed, using resized video.")
        st.warning("Credits overlay failed, proceeding without credits")
        final_file = resized_file
    
    if status_text: status_text.text("Cleaning up temporary files...")
    
    try:
        print("Cleaning up temporary files...")
        if os.path.exists(downloaded_file):
            os.remove(downloaded_file)
        if os.path.exists(trimmed_file) and trimmed_file != final_file:
            os.remove(trimmed_file)
        if os.path.exists(resized_file) and resized_file != final_file:
            os.remove(resized_file)
    except Exception:
        pass
    
    if status_text: status_text.text("Processing complete!")
    return final_file

def main():
    st.set_page_config(
        page_title="YouTube Clip Downloader",
        page_icon="🎬",
        layout="wide"
    )
    
    st.title("🎬 YouTube Clip Downloader & Resizer")
    st.markdown("Download YouTube clips and automatically resize them to 9:16 aspect ratio (1080x1920)")
    
    with st.form("clip_downloader_form"):
        st.subheader("Video Details")
        
        url = st.text_input(
            "YouTube URL",
            placeholder="https://www.youtube.com/watch?v=...",
            help="Enter the full YouTube video URL"
        )
        
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
        
        st.subheader("Optional: Browser Cookies")
        cookies_content = st.text_area(
            "Paste cookies.txt content",
            height=100,
            placeholder="# Netscape HTTP Cookie File\n# This is a generated file! Do not edit.\n\n.youtube.com\tTRUE\t/\tFALSE\t...",
            help="Paste the content of your cookies.txt file if the video requires authentication"
        )
        
        submitted = st.form_submit_button("Download & Process Clip", type="primary")
    
    if submitted:
        progress_bar = st.progress(0)
        status_text = st.empty()

        if not url:
            st.error("Please enter a YouTube URL")
            progress_bar.empty()
            status_text.empty()
            return
        
        if not start_time or not end_time:
            st.error("Please enter both start and end times")
            progress_bar.empty()
            status_text.empty()
            return
        
        try:
            parse_time(start_time)
            parse_time(end_time)
        except ValueError as e:
            st.error(f"Invalid time format: {e}")
            progress_bar.empty()
            status_text.empty()
            return
        
        try:
            with st.spinner("Downloading and processing video... Please wait."):
                processed_video_path = download_and_resize_clip(
                    url, start_time, end_time, 
                    cookies_content.strip() if cookies_content else None,
                    progress_bar, status_text
                )
                
                status_text.success("✅ Video processed successfully!")
                progress_bar.progress(1.0)
                
                st.success("✅ Video processed successfully!")
                
                st.subheader("Processed Video")
                
                col1, col2, col3 = st.columns([2, 1, 2])
                with col2:
                    with open(processed_video_path, 'rb') as video_file:
                        video_bytes = video_file.read()
                        st.video(video_bytes)
                
                filename = f"clip_{start_time.replace(':', '-')}_to_{end_time.replace(':', '-')}.mp4"
                st.download_button(
                    label="📥 Download Processed Video",
                    data=video_bytes,
                    file_name=filename,
                    mime="video/mp4"
                )
                
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
            if status_text: status_text.error(f"Error: {str(e)}")
            if progress_bar: progress_bar.empty()
    
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
