"""
WhatsApp notification module for SBR Autofill.
Sends completion notifications via WhatsApp Web using pywhatkit.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sbr_automation.autofill import AutofillStats

logger = logging.getLogger(__name__)


def format_notification_message(stats: AutofillStats, run_id: str, log_filename: str) -> str:
    """
    Format the WhatsApp notification message with autofill statistics.
    
    Args:
        stats: AutofillStats object containing success/error/skip counts
        run_id: Run identifier
        log_filename: Name of the log CSV file
        
    Returns:
        Formatted message string
    """
    total = stats.success_count + stats.error_count + stats.skip_count
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    message = f"""🤖 SBR Autofill Selesai

📊 Ringkasan:
Total: {total} baris
✅ Sukses: {stats.success_count}
❌ Error: {stats.error_count}
⏭️ Dilewati: {stats.skip_count}

🔖 Run ID: {run_id}
📝 Log: {log_filename}"""

    # Add error details if there are errors
    if stats.error_count > 0 and stats.recent_errors:
        message += "\n\n⚠️ Error Terakhir:"
        # Show up to 3-5 most recent errors
        for idx, error in enumerate(stats.recent_errors[:5], 1):
            # Truncate long error messages
            error_msg = error if len(error) <= 60 else error[:57] + "..."
            message += f"\n{idx}. {error_msg}"
    
    message += f"\n\n🕐 Selesai: {timestamp}"
    
    return message


def send_whatsapp_notification(
    phone_number: str,
    stats: AutofillStats,
    run_id: str,
    log_filename: str,
) -> bool:
    """
    Send WhatsApp notification with autofill completion summary.
    
    Args:
        phone_number: Target WhatsApp number (format: 081234567890 or +6281234567890)
        stats: AutofillStats object containing success/error/skip counts
        run_id: Run identifier
        log_filename: Name of the log CSV file
        
    Returns:
        True if notification was scheduled successfully, False otherwise
    """
    try:
        import pywhatkit
    except ImportError:
        logger.warning("pywhatkit tidak terinstall. Notifikasi WhatsApp dilewati.")
        logger.warning("Install dengan: pip install pywhatkit")
        return False
    
    # Normalize phone number
    normalized_phone = _normalize_phone_number(phone_number)
    if not normalized_phone:
        logger.error(f"Nomor WhatsApp tidak valid: {phone_number}")
        return False
    
    # Format message
    message = format_notification_message(stats, run_id, log_filename)
    
    # Send notification
    try:
        print("\n" + "=" * 72)
        print("📱 Mengirim notifikasi WhatsApp...")
        print(f"   Target: {phone_number}")
        print("   Browser DEFAULT akan terbuka dalam 15 detik")
        print()
        
        # Schedule message to be sent immediately (current time + 1 minute)
        now = datetime.now()
        hour = now.hour
        minute = now.minute + 1
        
        # Handle minute overflow
        if minute >= 60:
            minute = 0
            hour += 1
            if hour >= 24:
                hour = 0
        
        # Send via pywhatkit
        pywhatkit.sendwhatmsg(
            normalized_phone,
            message,
            hour,
            minute,
            wait_time=15,  # Wait 15 seconds before sending
            tab_close=True,  # Close tab after sending
            close_time=3,  # Close after 3 seconds
        )
        
        print(f"[WhatsApp] ✓ Pesan berhasil dijadwalkan untuk {hour:02d}:{minute:02d}")
        print("✓ Notifikasi WhatsApp berhasil dijadwalkan")
        print("=" * 72)
        
        return True
        
    except Exception as exc:
        logger.error(f"Gagal mengirim notifikasi WhatsApp: {exc}")
        print(f"\n⚠️ Gagal mengirim notifikasi WhatsApp: {exc}")
        return False


def _normalize_phone_number(phone: str) -> str:
    """
    Normalize phone number to international format.
    
    Args:
        phone: Phone number in various formats
        
    Returns:
        Normalized phone number with country code (+62...)
    """
    if not phone:
        return ""
    
    # Remove all non-digit characters
    digits = "".join(c for c in phone if c.isdigit())
    
    if not digits:
        return ""
    
    # Add country code if not present
    if digits.startswith("62"):
        return "+" + digits
    elif digits.startswith("0"):
        return "+62" + digits[1:]
    elif digits.startswith("8"):
        return "+62" + digits
    else:
        # Assume it already has country code
        return "+" + digits


def notify_autofill_complete(
    phone_number: str | None,
    stats: AutofillStats,
    run_id: str,
    log_filename: str,
    enabled: bool = True,
) -> None:
    """
    High-level function to send WhatsApp notification if enabled.
    
    Args:
        phone_number: Target WhatsApp number (None to skip)
        stats: AutofillStats object
        run_id: Run identifier
        log_filename: Log file name
        enabled: Whether notifications are enabled
    """
    if not enabled:
        logger.info("Notifikasi WhatsApp dinonaktifkan (--no-wa-notify)")
        return
    
    if not phone_number:
        logger.info("Nomor WhatsApp tidak dikonfigurasi. Notifikasi dilewati.")
        return
    
    send_whatsapp_notification(phone_number, stats, run_id, log_filename)
