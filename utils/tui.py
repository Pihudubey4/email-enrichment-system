import os
import sys
import time
import threading
from collections import deque
from typing import List, Dict, Any
from pathlib import Path

# Add root folder to path to allow importing config
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

class TerminalUI:
    """
    Console dashboard interface for the AI Email Enrichment System.
    Draws a real-time progress update panels matching the requested layout.
    """
    def __init__(self, filename: str, total_contacts: int, max_workers: int, total_missing_init: int) -> None:
        self.filename = filename
        self.total_contacts = total_contacts
        self.max_workers = max_workers
        self.total_missing = total_missing_init
        
        self.start_time = time.time()
        self.processed = 0
        self.found = 0
        self.not_found = 0
        self.errors = 0
        
        # Detailed metrics
        self.fast_path = 0
        self.ai_bypass = 0
        self.ai_inference = 0
        self.ollama_timeouts = 0
        self.ddg_queries = 0
        self.active_workers: Dict[str, Dict[str, Any]] = {}  # thread_name -> {"contact": str, "stage": str, "start_time": float}
        
        # Keep track of recent activities (thread-safe deque with max length 5)
        self.recent_activities = deque(maxlen=5)
        self.recent_activities.append("Initializing thread workers...")
        self._lock = threading.Lock()
        self._render()

    def update(self, name: str, email: str, status: str, error_msg: str = None) -> None:
        """Updates counts and appends to recent activity log, then prints dashboard."""
        with self._lock:
            self.processed += 1
            if status == "Valid":
                self.found += 1
                activity = f"[OK] {name:<30} {email}"
            elif status == "Invalid" or error_msg:
                self.errors += 1
                reason = error_msg or "invalid"
                activity = f"[ERR] {name:<29} ({reason})"
            else:
                self.not_found += 1
                activity = f"[--] {name:<30} (not found)"

            self.recent_activities.append(activity)
            self._render()

    def set_worker_status(self, thread_name: str, contact: str, stage: str) -> None:
        """Sets the active status of a thread worker slot and triggers a redraw."""
        with self._lock:
            self.active_workers[thread_name] = {
                "contact": contact,
                "stage": stage,
                "start_time": time.time()
            }
            self._render()

    def clear_worker_status(self, thread_name: str) -> None:
        """Clears the active status of a thread worker slot and triggers a redraw."""
        with self._lock:
            if thread_name in self.active_workers:
                del self.active_workers[thread_name]
            self._render()

    def increment_metric(self, name: str) -> None:
        """Thread-safely increments one of the advanced metrics and triggers a redraw."""
        with self._lock:
            if name == "fast_path":
                self.fast_path += 1
            elif name == "ai_bypass":
                self.ai_bypass += 1
            elif name == "ai_inference":
                self.ai_inference += 1
            elif name == "ollama_timeouts":
                self.ollama_timeouts += 1
            elif name == "ddg_queries":
                self.ddg_queries += 1
            self._render()

    def _render(self) -> None:
        """Clears screen and renders TUI dashboard."""
        # Use terminal ANSI sequences to clear screen and home cursor
        sys.stdout.write("\033[H\033[J")
        
        elapsed = time.time() - self.start_time
        elapsed_str = self._format_duration(elapsed)
        
        # Calculate rates and ETA
        rate_per_sec = self.processed / elapsed if elapsed > 0 else 0
        rate_per_hour = int(rate_per_sec * 3600)
        
        if rate_per_sec > 0:
            remaining = self.total_contacts - self.processed
            eta = remaining / rate_per_sec
            eta_str = self._format_duration(eta)
        else:
            eta_str = "--h --m --s"
            
        progress_pct = int((self.processed / self.total_contacts) * 100) if self.total_contacts > 0 else 0
        
        # Draw Progress Bar (50 characters wide)
        bar_len = 50
        filled_len = int(bar_len * self.processed / self.total_contacts) if self.total_contacts > 0 else 0
        bar = "=" * filled_len + "-" * (bar_len - filled_len)
        
        # Hit rate calculation
        processed_attempts = self.found + self.not_found
        hit_rate = (self.found / processed_attempts * 100) if processed_attempts > 0 else 0.0
        
        # Construct dashboard output
        lines = []
        lines.append("========================================================================")
        lines.append(" * CONTACT ENRICHMENT - LOCAL GEMMA INFERENCE MODE")
        lines.append("========================================================================")
        lines.append(f" File:        {self.filename}")
        lines.append(f" Workers:     {self.max_workers} active concurrent streams")
        lines.append(f" Model:       {config.MODEL_NAME} (Timeout: {config.TIMEOUT}s)")
        lines.append("------------------------------------------------------------------------")
        lines.append("")
        lines.append(" Progress:")
        lines.append(f"   [{bar}] {progress_pct}%")
        lines.append(f"   Processed: {self.processed}/{self.total_contacts}  (Total Missing: {self.total_missing - self.found})")
        lines.append(f"   Rate:      {rate_per_hour} contacts/hour  |  ETA: {eta_str}")
        lines.append(f"   Elapsed:   {elapsed_str}")
        lines.append("")
        lines.append(" Detailed Pipeline Metrics:")
        lines.append(f"   Fast-Path Validation (Skip LLM):   {self.fast_path:<5}")
        lines.append(f"   Regex Domain AI-Bypasses:          {self.ai_bypass:<5}")
        lines.append(f"   AI Inference Queries (Local LLM):  {self.ai_inference:<5}")
        lines.append(f"   Ollama Timeout Failures:           {self.ollama_timeouts:<5}")
        lines.append(f"   DuckDuckGo Search Queries:         {self.ddg_queries:<5}")
        lines.append("")
        lines.append(" Results:")
        lines.append(f"   Found:     {self.found:<5} |  Not found: {self.not_found:<5} |  Errors: {self.errors}")
        lines.append(f"   Hit Rate:  {hit_rate:.1f}%")
        lines.append("")
        lines.append(" Active Thread Channels:")
        
        # Format active workers sorted by thread name
        sorted_threads = sorted(self.active_workers.keys())
        for i in range(self.max_workers):
            if i < len(sorted_threads):
                t_name = sorted_threads[i]
                info = self.active_workers[t_name]
                w_dur = time.time() - info["start_time"]
                # Truncate contact name for layout safety
                contact_display = info["contact"]
                if len(contact_display) > 30:
                    contact_display = contact_display[:27] + "..."
                lines.append(f"   [Slot {i+1}] {info['stage']:<10}: {contact_display:<30} ({w_dur:.1f}s elapsed)")
            else:
                lines.append(f"   [Slot {i+1}] IDLE")
        
        lines.append("")
        lines.append(" Recent Activity:")
        for act in list(self.recent_activities):
            lines.append(f"   {act}")
        lines.append("")
        lines.append("========================================================================")
        
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()

    def _format_duration(self, seconds: float) -> str:
        """Converts float seconds to readable format (e.g. 10m 33s or 41h 27m 15s)."""
        sec = int(seconds)
        if sec < 60:
            return f"{sec}s"
        elif sec < 3600:
            m = sec // 60
            s = sec % 60
            return f"{m}m {s}s"
        else:
            h = sec // 3600
            m = (sec % 3600) // 60
            s = sec % 60
            return f"{h}h {m}m {s}s"
