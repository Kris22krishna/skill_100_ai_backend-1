from datetime import datetime
from zoneinfo import ZoneInfo

def get_kolkata_timestamp():
    tz = ZoneInfo("Asia/Kolkata")
    return datetime.now(tz=tz).strftime("%d-%m-%Y %I:%M %p")
    
