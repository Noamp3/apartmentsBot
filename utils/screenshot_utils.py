# utils/screenshot_utils.py
"""Utility functions for capturing, managing, and cleaning up Facebook post screenshots."""

import os
import shutil
from datetime import datetime, timedelta
from typing import List, Optional
from config import settings
from utils.logger import Loggers

log = Loggers.scraper()

SCREENSHOTS_BASE_DIR = os.path.join("data", "screenshots")


def get_listing_screenshot_dir(listing_id: str) -> str:
    """Get the local directory path where screenshots for a listing are saved."""
    return os.path.join(SCREENSHOTS_BASE_DIR, listing_id)


async def save_post_screenshot(post_element, listing_id: str) -> Optional[str]:
    """Capture a screenshot of the entire Facebook post element.
    
    Args:
        post_element: The Playwright ElementHandle for the post.
        listing_id: The unique listing ID.
        
    Returns:
        The file path to the saved screenshot, or None if failed.
    """
    try:
        target_dir = get_listing_screenshot_dir(listing_id)
        os.makedirs(target_dir, exist_ok=True)
        file_path = os.path.join(target_dir, "post.png")
        
        await post_element.screenshot(path=file_path)
        log.debug(f"Saved post screenshot to {file_path}")
        return file_path
    except Exception as e:
        log.warning(f"Failed to capture post screenshot for {listing_id}: {e}")
        return None


async def save_gallery_screenshots(post_element, listing_id: str) -> List[str]:
    """Find and capture screenshots of individual gallery images attached to a Facebook post.
    
    Args:
        post_element: The Playwright ElementHandle for the post.
        listing_id: The unique listing ID.
        
    Returns:
        List of file paths to saved gallery screenshots.
    """
    saved_paths = []
    try:
        target_dir = get_listing_screenshot_dir(listing_id)
        os.makedirs(target_dir, exist_ok=True)
        
        # Find all images in the post element
        img_elements = await post_element.query_selector_all("img")
        
        count = 0
        for img in img_elements:
            try:
                # Basic visibility check
                if not await img.is_visible():
                    continue
                
                # Check bounding box to filter out small icons/emojis/profile pictures
                box = await img.bounding_box()
                if not box:
                    continue
                
                # Facebook profile pictures are usually 32px or 40px, reactions are 16-24px.
                # Grid photos are typically larger (>= 100px width and height).
                if box["width"] < 100 or box["height"] < 100:
                    continue
                
                src = await img.get_attribute("src") or ""
                # Skip inline tracking pixels, emojis, or standard icons
                if "emoji" in src or "rsrc.php" in src or src.startswith("data:"):
                    continue
                
                file_path = os.path.join(target_dir, f"gallery_{count}.png")
                await img.screenshot(path=file_path)
                saved_paths.append(file_path)
                count += 1
                
                # Save at most 5 gallery images to avoid sending huge media groups
                if count >= 5:
                    break
            except Exception as img_err:
                log.debug(f"Failed to screenshot gallery image {count} for {listing_id}: {img_err}")
                
        if saved_paths:
            log.debug(f"Saved {len(saved_paths)} gallery screenshots for {listing_id}")
    except Exception as e:
        log.warning(f"Failed to capture gallery screenshots for {listing_id}: {e}")
        
    return saved_paths


def cleanup_screenshots(listing_id: str):
    """Delete all screenshot files and the directory for a specific listing.
    
    Args:
        listing_id: The unique listing ID.
    """
    try:
        target_dir = get_listing_screenshot_dir(listing_id)
        if os.path.exists(target_dir):
            shutil.rmtree(target_dir)
            log.debug(f"Cleaned up screenshots for listing {listing_id}")
    except Exception as e:
        log.error(f"Failed to clean up screenshots for {listing_id}: {e}")


def cleanup_old_screenshots(max_age_hours: Optional[int] = None):
    """Periodically cleans up leftover screenshot directories older than the maximum age.
    
    Args:
        max_age_hours: Maximum age of directories in hours. If None, uses configuration value.
    """
    try:
        if max_age_hours is None:
            max_age_hours = settings.SCREENSHOT_CLEANUP_MAX_AGE_HOURS
            
        if not os.path.exists(SCREENSHOTS_BASE_DIR):
            return
            
        now = datetime.now()
        cutoff = now - timedelta(hours=max_age_hours)
        
        removed_count = 0
        for item in os.listdir(SCREENSHOTS_BASE_DIR):
            item_path = os.path.join(SCREENSHOTS_BASE_DIR, item)
            if os.path.isdir(item_path):
                mtime = datetime.fromtimestamp(os.path.getmtime(item_path))
                if mtime < cutoff:
                    try:
                        shutil.rmtree(item_path)
                        removed_count += 1
                    except Exception as rm_err:
                        log.debug(f"Error removing old screenshot directory {item_path}: {rm_err}")
                        
        if removed_count > 0:
            log.info(f"Cleaned up {removed_count} old screenshot directories (older than {max_age_hours} hours)")
    except Exception as e:
        log.error(f"Failed to clean up old screenshots: {e}")
