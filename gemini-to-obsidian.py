"""
Enhanced Gemini to Obsidian Converter

This script converts a Google Takeout export of Gemini chat history into 
individual Markdown files formatted for Obsidian with proper YAML frontmatter,
clean formatting, and robust attachment handling.
"""
import json
import os
import re
import html2text
import shutil
import logging
import unicodedata
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional

# --- DEPENDENCY CHECK & INSTALLATION INSTRUCTIONS ---
try:
    from tqdm import tqdm
    import ijson
except ImportError:
    print("Required libraries not found.")
    print("Please install them by running: pip install tqdm ijson html2text")
    exit()

# --- CONFIGURATION ---

# 1. Set the path to the ROOT of your unzipped Google Takeout folder.
TAKEOUT_ROOT_PATH = 'C:/Users/cryri/Downloads/Takeout'

# 2. Set the path to your Obsidian vault's import folder.
OBSIDIAN_OUTPUT_PATH = 'C:/Users/cryri/Documents/ObsidianVault/Gemini Imports'

# 3. Add default tags that will be included in every created note.
DEFAULT_TAGS = ['ai/gemini/export']

# 4. Set the number of minutes of inactivity before starting a new conversation.
SESSION_TIMEOUT_MINUTES = 30

# 5. Set the maximum number of keyword-based tags to generate per note.
MAX_KEYWORDS_PER_NOTE = 10

# 6. Organize output files into subfolders by date (e.g., 2025/09/).
ORGANIZE_BY_DATE = True

# 7. Simulate the conversion without writing files to preview the output.
DRY_RUN = False

# 8. Set to True to print detailed information about skipped records.
DEBUG_MODE = False

# --- END OF CONFIGURATION ---

# --- LOGGING SETUP ---
logging.basicConfig(
    level=logging.DEBUG if DEBUG_MODE else logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- CONSTANTS ---
STOP_WORDS = {
    'a', 'about', 'above', 'after', 'again', 'against', 'all', 'am', 'an', 'and', 'any', 'are', "aren't", 'as', 'at',
    'be', 'because', 'been', 'before', 'being', 'below', 'between', 'both', 'but', 'by', 'can', "can't", 'cannot',
    'could', "couldn't", 'did', "didn't", 'do', 'does', "doesn't", 'doing', 'don', "don't", 'down', 'during', 'each',
    'few', 'for', 'from', 'further', 'had', "hadn't", 'has', "hasn't", 'have', "haven't", 'having', 'he', "he'd",
    "he'll", "he's", 'her', 'here', "here's", 'hers', 'herself', 'him', 'himself', 'his', 'how', "how's", 'i', "i'd",
    "i'll", "i'm", "i've", 'if', 'in', 'into', 'is', "isn't", 'it', "it's", 'its', 'itself', 'let', "let's", 'me',
    'more', 'most', "mustn't", 'my', 'myself', 'no', 'nor', 'not', 'of', 'off', 'on', 'once', 'only', 'or', 'other',
    'ought', 'our', 'ourselves', 'out', 'over', 'own', 'same', 'shan', "shan't", 'she', "she'd", "she'll",
    "she's", 'should', "shouldn't", 'so', 'some', 'such', 'than', 'that', "that's", 'the', 'their', 'theirs', 'them',
    'themselves', 'then', 'there', "there's", 'these', 'they', "they'd", "they'll", "they're", "they've", 'this',
    'those', 'through', 'to', 'too', 'under', 'until', 'up', 'very', 'was', "wasn't", 'we', "we'd", "we'll", "we're",
    "we've", 'were', "weren't", 'what', "what's", 'when', "when's", 'where', "where's", 'which', 'while', 'who',
    "who's", 'whom', 'why', "why's", 'with', "won't", 'would', "wouldn't", 'you', "you'd", "you'll", "you're",
    "you've", 'your', 'yours', 'yourself', 'yourselves', 'gemini', 'apps', 'bard', 'html', 'google', 'please',
    'thank', 'thanks', 'help', 'need', 'want', 'get', 'make', 'know', 'think', 'like', 'use', 'work', 'see', 'say'
}

IMAGE_EXTENSIONS = ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.svg', '.webp', '.tiff', '.tif']
DOCUMENT_EXTENSIONS = ['.pdf', '.doc', '.docx', '.txt', '.rtf', '.odt']
AUDIO_EXTENSIONS = ['.mp3', '.wav', '.ogg', '.m4a', '.aac', '.flac']
VIDEO_EXTENSIONS = ['.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv']

# --- HELPER FUNCTIONS ---

def sanitize_filename(name: str) -> str:
    """Removes characters that are invalid for file names and normalizes Unicode."""
    if not name:
        return "untitled"
    
    # Normalize Unicode characters
    name = unicodedata.normalize('NFKD', name)
    
    # Replace problematic characters
    name = name.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = re.sub(r'\.{2,}', '.', name)
    name = re.sub(r'\s+', ' ', name)  # Multiple spaces to single space
    
    # Remove leading/trailing spaces and dots
    name = name.strip(' .')
    
    # Ensure we don't exceed filename length limits
    return name[:150] if name else "untitled"

def get_unique_filename(base_path: str, filename: str) -> str:
    """Generate a unique filename by appending a counter if needed."""
    counter = 1
    base, ext = os.path.splitext(filename)
    base_path = Path(base_path)
    base_path.mkdir(parents=True, exist_ok=True)
    
    original_filename = filename
    while (base_path / filename).exists():
        filename = f"{base}_{counter}{ext}"
        counter += 1
    return filename

def sanitize_tag(name: str) -> str:
    """Converts a string into a valid Obsidian tag, safe for YAML."""
    if not name:
        return ""
    
    # Normalize Unicode and convert to lowercase
    name = unicodedata.normalize('NFKD', name).lower()
    
    # Keep only alphanumeric, hyphens, underscores, and forward slashes
    sanitized = re.sub(r'[^a-z0-9\-_/]', '', name)
    
    # Remove multiple consecutive hyphens
    sanitized = re.sub(r'-{2,}', '-', sanitized)
    
    # Remove leading/trailing hyphens and slashes
    sanitized = sanitized.strip('-/')
    
    # Ensure tag isn't empty and doesn't start with a number
    if not sanitized or sanitized[0].isdigit():
        return ""
    
    return sanitized

def extract_keywords(text: str) -> List[str]:
    """Extracts meaningful keywords from text for use as tags."""
    if not text:
        return []
    
    # Normalize and clean text
    text = unicodedata.normalize('NFKD', text.lower())
    text = re.sub(r'[^\w\s]', ' ', text)
    words = text.split()
    
    # Filter out stop words and short words
    keywords = [
        word for word in words 
        if word not in STOP_WORDS 
        and len(word) > 2 
        and not word.isdigit()
        and word.isalpha()  # Only alphabetic words
    ]
    
    # Count frequency and take most common
    from collections import Counter
    word_counts = Counter(keywords)
    return [word for word, count in word_counts.most_common(MAX_KEYWORDS_PER_NOTE)]

def parse_datetime(timestamp_str: str) -> Optional[datetime]:
    """Safely parse an ISO timestamp string with multiple format support."""
    if not timestamp_str:
        return None
    
    formats = [
        '%Y-%m-%dT%H:%M:%S.%fZ',
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%dT%H:%M:%S.%f%z',
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%d %H:%M:%S',
    ]
    
    # Handle 'Z' timezone indicator
    timestamp_str = timestamp_str.replace('Z', '+00:00')
    
    for fmt in formats:
        try:
            return datetime.fromisoformat(timestamp_str) if '+' in timestamp_str else datetime.strptime(timestamp_str, fmt)
        except (ValueError, TypeError):
            continue
    
    logger.warning(f"Could not parse timestamp: {timestamp_str}")
    return None

def find_attachment_file(takeout_root: str, relative_path: str) -> Optional[str]:
    """Find an attachment file with robust search fallback."""
    if not relative_path:
        return None
    
    # Try the direct path first
    source_path = Path(takeout_root) / relative_path
    if source_path.exists():
        return str(source_path)
    
    # Fall back to recursive search by filename
    filename = Path(relative_path).name
    takeout_path = Path(takeout_root)
    
    for file_path in takeout_path.rglob(filename):
        if file_path.is_file():
            logger.info(f"Found attachment via search: {file_path}")
            return str(file_path)
    
    logger.warning(f"Attachment not found: {relative_path}")
    return None

def process_attachment(attachment_info: Dict[str, Any], takeout_root: str, attachments_output_path: str) -> str:
    """Process a single attachment and return markdown link."""
    try:
        # Extract attachment path - handle different possible structures
        attachment_path = None
        if 'url' in attachment_info:
            # Extract path from URL
            url = attachment_info['url']
            if 'takeout-download' in url:
                # Extract the path after the takeout identifier
                path_match = re.search(r'takeout-download[^/]*/(.+)', url)
                if path_match:
                    attachment_path = path_match.group(1)
        
        if not attachment_path and 'path' in attachment_info:
            attachment_path = attachment_info['path']
        
        if not attachment_path:
            return f"*[Attachment: {attachment_info.get('name', 'Unknown')} - Path not found]*"
        
        source_file = find_attachment_file(takeout_root, attachment_path)
        if not source_file:
            return f"*[Attachment: {attachment_info.get('name', 'Unknown')} - File not found]*"
        
        # Determine file type and create appropriate link
        file_ext = Path(source_file).suffix.lower()
        filename = Path(source_file).name
        safe_filename = sanitize_filename(filename)
        
        # Copy file to attachments directory
        dest_path = Path(attachments_output_path) / safe_filename
        dest_path = Path(attachments_output_path) / get_unique_filename(attachments_output_path, safe_filename)
        
        if not DRY_RUN:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, dest_path)
        
        # Create appropriate markdown link based on file type
        relative_path = f"_attachments/{dest_path.name}"
        
        if file_ext in IMAGE_EXTENSIONS:
            return f"![[{relative_path}]]"
        elif file_ext in AUDIO_EXTENSIONS:
            return f"![[{relative_path}]]"
        elif file_ext in VIDEO_EXTENSIONS:
            return f"![[{relative_path}]]"
        else:
            return f"[[{relative_path}|{safe_filename}]]"
            
    except Exception as e:
        logger.error(f"Error processing attachment: {e}")
        return f"*[Attachment: {attachment_info.get('name', 'Unknown')} - Error processing]*"

def clean_html_content(html_content: str) -> str:
    """Clean and convert HTML content to markdown with better formatting."""
    if not html_content:
        return ""
    
    try:
        # Handle dict/list structures that might contain HTML
        if isinstance(html_content, dict):
            if 'html' in html_content:
                html_content = html_content['html']
            else:
                html_content = ''.join(str(v) for v in html_content.values() if isinstance(v, str))
        elif isinstance(html_content, list):
            html_content = '\n'.join(str(item) for item in html_content)
        
        html_content = str(html_content)
        
        # Remove common artifacts from Takeout export
        html_content = re.sub(r"^\{'html':\s*'", '', html_content)
        html_content = re.sub(r"'\}$", '', html_content)
        html_content = html_content.replace("\\n", "\n")
        html_content = html_content.replace("\\'", "'")
        html_content = html_content.replace('\\"', '"')
        
        # Clean up problematic characters that might break regex
        html_content = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', html_content)  # Remove control characters
        html_content = re.sub(r'\s+', ' ', html_content)  # Normalize whitespace
        
        # If content is very short or just whitespace, return early
        if len(html_content.strip()) < 3:
            return html_content.strip()
        
        # Initialize html2text with better settings
        h = html2text.HTML2Text()
        h.body_width = 0  # Don't wrap lines
        h.protect_links = True
        h.wrap_links = False
        h.unicode_snob = True
        h.escape_snob = True
        h.ignore_emphasis = False
        h.ignore_links = False
        h.ignore_images = False
        h.default_image_alt = ""
        
        # Pre-process HTML to fix common issues
        html_content = html_content.replace('</p><p>', '</p>\n\n<p>')
        html_content = html_content.replace('<br>', '\n')
        html_content = html_content.replace('<br/>', '\n')
        html_content = html_content.replace('<br />', '\n')
        
        # Convert to markdown
        markdown = h.handle(html_content)
        
        # Post-process markdown to clean up formatting
        markdown = re.sub(r'\n{3,}', '\n\n', markdown)  # Max 2 consecutive newlines
        markdown = re.sub(r'[ \t]+\n', '\n', markdown)  # Remove trailing whitespace
        markdown = re.sub(r'^\s*\n', '', markdown)  # Remove leading newlines
        markdown = markdown.strip()
        
        return markdown
        
    except Exception as e:
        # If HTML parsing fails, return the cleaned raw content
        logger.warning(f"HTML parsing failed, returning raw content: {e}")
        # Clean the raw content as best we can
        clean_content = re.sub(r'<[^>]+>', '', str(html_content))  # Strip HTML tags
        clean_content = re.sub(r'\s+', ' ', clean_content)  # Normalize whitespace
        return clean_content.strip()

def load_records_from_stream(json_path: str) -> List[Dict[str, Any]]:
    """Load and filter Gemini records from a large JSON file using streaming."""
    records = []
    
    try:
        with open(json_path, 'rb') as f:
            parser = ijson.items(f, 'item')
            for item in tqdm(parser, desc="Loading and parsing JSON records"):
                # Check if this is a Gemini/Bard record
                header = item.get('header', '')
                products = item.get('products', [])
                title = item.get('title', '')
                
                is_gemini_record = (
                    'Gemini Apps' in header or 
                    'Gemini' in products or 
                    'Bard' in products or
                    'gemini.google.com' in str(item.get('titleUrl', ''))
                )
                
                if is_gemini_record:
                    timestamp = parse_datetime(item.get('time'))
                    if timestamp:
                        item['parsed_time'] = timestamp
                        records.append(item)
                    elif DEBUG_MODE:
                        logger.debug(f"Skipped record with invalid timestamp: {item.get('time')}")
                        
        logger.info(f"Loaded {len(records)} valid Gemini records from stream.")
        return records
        
    except ijson.JSONError as e:
        logger.error(f"Error parsing JSON file: {e}")
        return []
    except FileNotFoundError:
        logger.error(f"JSON file not found at '{json_path}'")
        return []
    except Exception as e:
        logger.error(f"Unexpected error loading records: {e}")
        return []

def extract_chat_title(record: Dict[str, Any]) -> str:
    """Extract a clean chat title from the record."""
    title = record.get('title', '')
    
    # Remove common prefixes
    title = re.sub(r'^Prompted\s+', '', title, flags=re.IGNORECASE)
    title = re.sub(r'^Asked\s+', '', title, flags=re.IGNORECASE)
    title = re.sub(r'^Search\s+', '', title, flags=re.IGNORECASE)
    
    # Clean up the title
    title = title.strip()
    
    # If title is too long, truncate at a reasonable point
    if len(title) > 80:
        # Try to truncate at a word boundary
        truncated = title[:77]
        if ' ' in truncated:
            last_space = truncated.rfind(' ')
            title = title[:last_space] + "..."
        else:
            title = title[:77] + "..."
    
    return title if title else "Untitled Chat"

def create_yaml_frontmatter(title: str, creation_time: datetime, source_url: str, tags: List[str]) -> str:
    """Create properly formatted YAML frontmatter."""
    # Escape title for YAML
    safe_title = title.replace('"', '""').replace('\n', ' ').replace('\r', ' ').strip()
    if len(safe_title) > 100:
        safe_title = safe_title[:97] + "..."
    
    formatted_date = creation_time.strftime('%Y-%m-%d %H:%M:%S')
    
    yaml_lines = [
        "---",
        f'title: "{safe_title}"',
        f"created: {formatted_date}",
        f"source: {source_url}" if source_url else "source: ''",
        "tags:"
    ]
    
    # Add tags with proper YAML formatting
    for tag in tags:
        if tag:  # Only add non-empty tags
            yaml_lines.append(f"  - {tag}")
    
    yaml_lines.append("---")
    return "\n".join(yaml_lines)

def convert_takeout_to_obsidian():
    """Main conversion function with improved error handling and formatting."""
    logger.info("--- Starting Enhanced Gemini to Obsidian Conversion ---")
    
    if DRY_RUN:
        logger.info("*** DRY RUN MODE ENABLED: No files will be written. ***")

    # Validate paths
    takeout_path = Path(TAKEOUT_ROOT_PATH)
    if not takeout_path.exists():
        logger.error(f"Takeout root path does not exist: {takeout_path}")
        return

    json_path = takeout_path / 'My Activity' / 'Gemini Apps' / 'MyActivity.json'
    if not json_path.exists():
        logger.error(f"Gemini activity file not found at: {json_path}")
        return

    output_path = Path(OBSIDIAN_OUTPUT_PATH)
    attachments_output_path = output_path / '_attachments'

    # Load and process records
    valid_records = load_records_from_stream(str(json_path))
    if not valid_records:
        logger.warning("No valid Gemini records found. Exiting.")
        return

    # Sort records by time
    valid_records.sort(key=lambda x: x['parsed_time'])
    
    # Group records into conversations based on time gaps
    conversations = []
    if valid_records:
        current_conversation = [valid_records[0]]
        
        for i in range(1, len(valid_records)):
            prev_record = valid_records[i-1]
            current_record = valid_records[i]
            time_diff = current_record['parsed_time'] - prev_record['parsed_time']
            
            if time_diff > timedelta(minutes=SESSION_TIMEOUT_MINUTES):
                conversations.append(current_conversation)
                current_conversation = [current_record]
            else:
                current_conversation.append(current_record)
        
        conversations.append(current_conversation)

    logger.info(f"Grouped {len(valid_records)} records into {len(conversations)} conversations.")

    # Create output directories
    if not DRY_RUN:
        output_path.mkdir(parents=True, exist_ok=True)
        attachments_output_path.mkdir(parents=True, exist_ok=True)

    # Process each conversation
    warnings = []
    errors = []
    
    for i, conversation in enumerate(tqdm(conversations, desc="Converting conversations to Markdown")):
        try:
            first_message = conversation[0]
            
            # Extract clean conversation title from the first message
            chat_title = extract_chat_title(first_message)
            
            creation_time = first_message['parsed_time']
            source_url = first_message.get('titleUrl', '')
            
            # Build conversation content
            full_conversation_text = ""
            markdown_content = f"# {chat_title}\n\n"
            
            for j, message in enumerate(conversation):
                # Extract prompt and response
                prompt = message.get('title', '').replace('Prompted ', '', 1).strip()
                response_raw = message.get('safeHtmlItem', '')
                
                # Convert to clean markdown
                prompt_md = clean_html_content(prompt) if prompt else ""
                response_md = clean_html_content(response_raw) if response_raw else ""
                
                # Add to full text for keyword extraction
                full_conversation_text += f"{prompt_md} {response_md} "
                
                # Add user message
                if prompt_md:
                    markdown_content += f"## You\n\n{prompt_md}\n\n"
                
                # Process attachments
                attachments_md = ""
                if 'attachmentInfo' in message and isinstance(message['attachmentInfo'], list):
                    for attachment in message['attachmentInfo']:
                        attachment_md = process_attachment(attachment, str(takeout_path), str(attachments_output_path))
                        attachments_md += f"{attachment_md}\n\n"
                
                if attachments_md:
                    markdown_content += f"{attachments_md}"
                
                # Add Gemini response
                if response_md or attachments_md:
                    markdown_content += f"---\n\n## Gemini\n\n{response_md}\n\n"
            
            # Extract keywords and create tags
            keywords = extract_keywords(full_conversation_text)
            valid_tags = [sanitize_tag(kw) for kw in keywords if sanitize_tag(kw)]
            all_tags = list(dict.fromkeys(DEFAULT_TAGS + valid_tags))  # Remove duplicates while preserving order
            
            # Create YAML frontmatter
            yaml_frontmatter = create_yaml_frontmatter(chat_title, creation_time, source_url, all_tags)
            
            # Add footer
            footer = f"\n---\n*Imported from Google Takeout on {datetime.now().strftime('%Y-%m-%d')}*"
            
            # Determine output directory
            if ORGANIZE_BY_DATE:
                date_dir = output_path / creation_time.strftime('%Y') / creation_time.strftime('%m')
            else:
                date_dir = output_path
            
            # Create filename without date
            base_filename = sanitize_filename(chat_title) + ".md"
            safe_filename = get_unique_filename(str(date_dir), base_filename)
            filepath = date_dir / safe_filename
            
            # Write file
            if not DRY_RUN:
                date_dir.mkdir(parents=True, exist_ok=True)
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(yaml_frontmatter + "\n\n" + markdown_content + footer)
            else:
                logger.info(f"Would create: {filepath}")
                
        except Exception as e:
            error_msg = f"Error processing conversation {i+1}: {e}"
            logger.error(error_msg)
            errors.append(error_msg)

    # Final summary
    print()
    logger.info("--- Conversion Complete ---")
    logger.info(f"📊 Processed {len(valid_records)} total records.")
    logger.info(f"✅ {'[Dry Run] Would have created' if DRY_RUN else 'Successfully created'} {len(conversations)} conversation files.")
    
    if warnings:
        logger.warning(f"⚠️  {len(warnings)} warnings encountered:")
        for warning in warnings[:5]:  # Show first 5 warnings
            logger.warning(f"  - {warning}")
        if len(warnings) > 5:
            logger.warning(f"  ... and {len(warnings) - 5} more")
    
    if errors:
        logger.error(f"❌ {len(errors)} errors encountered:")
        for error in errors[:5]:  # Show first 5 errors
            logger.error(f"  - {error}")
        if len(errors) > 5:
            logger.error(f"  ... and {len(errors) - 5} more")
    
    if not warnings and not errors:
        logger.info("🎉 Conversion completed without issues!")

if __name__ == "__main__":
    convert_takeout_to_obsidian()