#!/usr/bin/env python3
import os
import sys
import subprocess

# ========================================================
# 0. AUTOMATIC VIRTUAL ENVIRONMENT BOOTSTRAPPER
# ========================================================
VENV_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "env")

if sys.prefix == sys.base_prefix:
    if not os.path.exists(VENV_DIR):
        print("🚀 Virtual environment not found. Building locally at ./env...")
        subprocess.run([sys.executable, "-m", "venv", VENV_DIR], check=True)
        
        print("📦 Installing core audio & automation dependencies...")
        pip_path = os.path.join(VENV_DIR, "bin", "pip")
        subprocess.run([pip_path, "install", "numpy", "sounddevice", "aubio", "pynput"], check=True)
        print("✅ Environment setup complete!")

    python_path = os.path.join(VENV_DIR, "bin", "python")
    os.execv(python_path, [python_path] + sys.argv)

# ========================================================
# 1. CORE PROGRAM DEPENDENCIES & TERMINAL PROTECTION MODES
# ========================================================
import numpy as np
import sounddevice as sd
import aubio
from pynput import keyboard as pynput_keyboard
from pynput.keyboard import Controller, Key
import queue
import threading
import time
import json

# Terminal control modules for suppressing ghost echo inputs
if os.name != 'nt':
    import termios
    import tty

def silence_terminal_echo(disable=True):
    """Completely turns off terminal character echoing to prevent leaking characters to bash."""
    if os.name == 'nt':
        return
    try:
        fd = sys.stdin.fileno()
        new_settings = termios.tcgetattr(fd)
        if disable:
            new_settings[3] = new_settings[3] & ~termios.ECHO
        else:
            new_settings[3] = new_settings[3] | termios.ECHO
        termios.tcsetattr(fd, termios.TCSADRAIN, new_settings)
    except Exception:
        pass

def purge_input_buffer():
    """Flushes any pending ghost keystrokes stuck in the stdin queue loop."""
    if os.name == 'nt':
        import msvcrt
        while msvcrt.kbhit():
            msvcrt.getch()
    else:
        try:
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
        except Exception:
            pass

keyboard_controller = Controller()

# ========================================================
# 2. FILE SYSTEM LAYOUT & CONFIGURATION MANAGEMENT
# ========================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LAYOUTS_DIR = os.path.join(BASE_DIR, "layouts")
TABS_DIR = os.path.join(BASE_DIR, "tabs")
TUNINGS_DIR = os.path.join(BASE_DIR, "tunings")
LAST_LAYOUT_CFG = os.path.join(BASE_DIR, ".last_layout.cfg")
SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")

os.makedirs(LAYOUTS_DIR, exist_ok=True)
os.makedirs(TABS_DIR, exist_ok=True)
os.makedirs(TUNINGS_DIR, exist_ok=True)

DEFAULT_TUNING_PRESETS = {
    "1": {"name": "STANDARD",       "notes": ["E2", "A2", "D3", "G3", "B3", "E4"]},
    "2": {"name": "DROP D",         "notes": ["D2", "A2", "D3", "G3", "B3", "E4"]},
    "3": {"name": "DADGAD",         "notes": ["D2", "A2", "D3", "G3", "A3", "D4"]},
    "4": {"name": "HALF-STEP DOWN", "notes": ["D#2","G#2","C#3","F#3","A#3","D#4"]},
    "5": {"name": "FULL-STEP DOWN", "notes": ["D2", "G2", "C3", "F3", "A3", "D4"]},
    "6": {"name": "DROP C",         "notes": ["C2", "G2", "C3", "F3", "A3", "D4"]},
    "7": {"name": "OPEN G",         "notes": ["D2", "G2", "D3", "G3", "B3", "D4"]},
    "8": {"name": "OPEN D",         "notes": ["D2", "A2", "D3", "F#3","A3", "D4"]},
    "9": {"name": "OPEN C",         "notes": ["C2", "G2", "C3", "G3", "C4", "E4"]},
    "10": {"name": "OPEN E",        "notes": ["E2", "B2", "E3", "G#3","B3", "E4"]},
    "11": {"name": "OPEN A",        "notes": ["E2", "A2", "C#3","E3", "A3", "E4"]},
    "12": {"name": "CELTIC",        "notes": ["D2", "A2", "D3", "D3", "A3", "D4"]},
}

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

CHROMATIC_CHAR_POOL = [
    "a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m", 
    "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z",
    "1", "2", "3", "4", "5", "6", "7", "8", "9", "0",
    "-", "=", "[", "]", ";", "'", ",", ".", "/", "\\", "`",
    "space", "backspace", "tab", "enter"
]

TUNING_PRESETS = {}

def load_all_tunings():
    global TUNING_PRESETS
    existing_files = [f for f in os.listdir(TUNINGS_DIR) if f.endswith(".json")]
    if not existing_files:
        for k, v in DEFAULT_TUNING_PRESETS.items():
            filename = f"{k.zfill(2)}_{v['name'].lower().replace(' ', '_')}.json"
            with open(os.path.join(TUNINGS_DIR, filename), "w") as f:
                json.dump(v, f, indent=4)
        existing_files = [f for f in os.listdir(TUNINGS_DIR) if f.endswith(".json")]
        
    TUNING_PRESETS.clear()
    for filename in sorted(existing_files):
        path = os.path.join(TUNINGS_DIR, filename)
        try:
            with open(path, "r") as f:
                data = json.load(f)
                key_id = filename.split("_")[0].lstrip("0")
                if not key_id: key_id = "0"
                TUNING_PRESETS[key_id] = (data["name"], data["notes"])
        except Exception:
            pass

load_all_tunings()

def load_settings():
    default_settings = {"device_index": None}
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return default_settings
    return default_settings

def save_settings(settings_data):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings_data, f, indent=4)

SETTINGS = load_settings()

def note_to_midi(note_name):
    if not note_name: return 0
    name = note_name[:-1]
    octave = int(note_name[-1])
    return 12 * (octave + 1) + NOTE_NAMES.index(name)

def midi_to_note_name(midi_num):
    return f"{NOTE_NAMES[midi_num % 12]}{ (midi_num // 12) - 1 }"

def note_to_hz(note_name):
    midi_num = note_to_midi(note_name)
    return 440.0 * (2.0 ** ((midi_num - 69) / 12.0))

def get_fretboard_notes(tuning_key, max_frets):
    base_strings = TUNING_PRESETS.get(tuning_key, ("STANDARD", ["E2", "A2", "D3", "G3", "B3", "E4"]))[1]
    fretboard = []
    for string_note in base_strings:
        base_midi = note_to_midi(string_note)
        string_frets = [midi_to_note_name(base_midi + fret) for fret in range(max_frets + 1)]
        fretboard.append(string_frets)
    return fretboard

def generate_maximalist_mappings(tuning_key, max_frets):
    fret_matrix = get_fretboard_notes(tuning_key, max_frets)
    mappings = {}
    char_idx = 0
    pool_len = len(CHROMATIC_CHAR_POOL)
    for s_idx in range(6):
        for f_idx in range(max_frets + 1):
            note_name = fret_matrix[s_idx][f_idx]
            if note_name not in mappings:
                mappings[note_name] = CHROMATIC_CHAR_POOL[char_idx % pool_len]
                char_idx += 1
    return mappings

def load_last_used_layout_name():
    if os.path.exists(LAST_LAYOUT_CFG):
        with open(LAST_LAYOUT_CFG, "r") as f:
            name = f.read().strip()
            if os.path.exists(os.path.join(LAYOUTS_DIR, name + ".json")):
                return name
    return "chromatic_maximalist"

def save_last_used_layout_name(name):
    with open(LAST_LAYOUT_CFG, "w") as f:
        f.write(name)

def load_layout_file(name):
    path = os.path.join(LAYOUTS_DIR, name + ".json")
    default_structure = {"tuning": "1", "max_frets": 22, "mappings": {}}
    if name == "chromatic_maximalist" and not os.path.exists(path):
        default_structure["mappings"] = generate_maximalist_mappings("1", 22)
        save_layout_file(name, default_structure)
        return default_structure
    if not os.path.exists(path):
        return default_structure
    try:
        with open(path, "r") as f:
            data = json.load(f)
            if "max_frets" not in data: data["max_frets"] = 22
            if "mappings" not in data: data["mappings"] = {}
            if not data["mappings"] and name == "chromatic_maximalist":
                data["mappings"] = generate_maximalist_mappings(data.get("tuning", "1"), data["max_frets"])
                save_layout_file(name, data)
            return data
    except Exception:
        return default_structure

def save_layout_file(name, data):
    path = os.path.join(LAYOUTS_DIR, name + ".json")
    if "mappings" not in data:
        data["mappings"] = {}
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

def get_parsed_runtime_mappings(layout_data):
    raw_map = layout_data.get("mappings", {})
    parsed_map = {}
    for k, v in raw_map.items():
        if v == "space": parsed_map[k] = Key.space
        elif v == "backspace": parsed_map[k] = Key.backspace
        elif v == "tab": parsed_map[k] = Key.tab
        elif v == "enter": parsed_map[k] = Key.enter
        else: parsed_map[k] = v
    return parsed_map

def ensure_sample_tabs_exist():
    tab_files = [f for f in os.listdir(TABS_DIR) if f.endswith(".txt")]
    if not tab_files:
        sample_path = os.path.join(TABS_DIR, "seven_nation_army.txt")
        sample_content = (
            "TUNING: 1\n"
            "--- SEVEN NATION ARMY (RIFF DEMO) ---\n\n"
            "e|-------------------------------------|\n"
            "B|-------------------------------------|\n"
            "G|-------------------------------------|\n"
            "D|---7-----7---9---7---5---4-----------|\n"
            "A|-------------------------------------|\n"
            "E|-------------------------------------|\n"
        )
        with open(sample_path, "w") as f:
            f.write(sample_content)

ACTIVE_LAYOUT_NAME = load_last_used_layout_name()
CURRENT_LAYOUT_DATA = load_layout_file(ACTIVE_LAYOUT_NAME)
NOTE_MAPPING = get_parsed_runtime_mappings(CURRENT_LAYOUT_DATA)
ensure_sample_tabs_exist()

# ========================================================
# 3. AUDIO INTERFACE ROUTING
# ========================================================
def auto_discover_input_device():
    if SETTINGS.get("device_index") is not None:
        try:
            dev = sd.query_devices(SETTINGS["device_index"], 'input')
            if dev['max_input_channels'] > 0:
                return SETTINGS["device_index"]
        except Exception:
            pass
    devices = sd.query_devices()
    for idx, dev in enumerate(devices):
        if dev['max_input_channels'] > 0:
            name_lower = dev['name'].lower()
            if "spider" in name_lower or "line 6" in name_lower or "line6" in name_lower:
                SETTINGS["device_index"] = idx
                save_settings(SETTINGS)
                return idx
    default_input = sd.default.device[0]
    if default_input >= 0:
        return default_input
    for idx, dev in enumerate(devices):
        if dev['max_input_channels'] > 0:
            return idx
    return None

DEVICE_INDEX = auto_discover_input_device()
HOP_SIZE = 1024          
WIN_SIZE = 4096          
SAMPLE_RATE = 44100

audio_queue = queue.Queue()
pitch_detector = aubio.pitch("default", WIN_SIZE, HOP_SIZE, SAMPLE_RATE)
pitch_detector.set_unit("Hz")
pitch_detector.set_tolerance(0.65)  
pitch_detector.set_silence(-42)    

INITIAL_STRIKE_CAGE = 0.220  
OUTPUT_PAUSE_MS = 0.030  
DEFAULT_SPIKE_RATIO = 1.15     
LOW_E_SPIKE_RATIO = 1.35       

last_strike_time = 0.0
previous_volume = 0.0          
current_active_note = None  

# GLOBAL STATE CONTROL
CURRENT_STATE = "MENU" 
SELECTED_LAYOUT_TO_VIEW = ""
SELECTED_TAB_FILE_NAME = ""
LOADED_TAB_DATA = {"tuning": "1", "content": []}
audio_stream = None

# DIGITAL PYNPUT CAPTURE BUFFER
INPUT_BUFFER = ""
WIZARD_STAGE = 0
WIZARD_DATA = {}

RECORDING_TUNING_KEY = "1"
RECORDED_TAB_MATRIX = [[] for _ in range(6)]
MODIFIER_QUEUE = []
LAST_DETECTED_MIDI = None
LAST_DETECTED_STRING = None
LAST_DETECTED_FRET = None

TARGET_TUNING_KEY = "1"
LIVE_TRACKED_PITCH = 0.0
LIVE_TRACKED_NOTE = ""

def clear_terminal():
    os.system('cls' if os.name == 'nt' else 'clear')

def get_terminal_width():
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 65

# ========================================================
# UI GRAPHICS RENDERING SCHEMATICS
# ========================================================
def show_main_menu():
    clear_terminal()
    w = min(get_terminal_width(), 70)
    print("=" * w)
    print(f" 🛠️  GUITAR KEYBOARD HUB | ACTIVE: [{ACTIVE_LAYOUT_NAME.upper()}]".center(w)[:w])
    print("=" * w)
    print(" [1]  Launch IDE Workspace Keyboard Automation Mode")
    print(" [2]  Open Multi-Tuning Chromatic Dashboard (Hz Targets)")
    print(" [3]  Manage Keyboard Layouts Profiles")
    print(" [4]  Open Guitar Tablature Archive Reader")
    print(" [5]  Launch Live Audio Guitar Tab Creator/Editor")
    print(" [6]  Open Instrument Tuning Matrix Manager")
    print(" [7]  Open System Settings Configuration")
    print(" [8]  Exit Script")
    print("-" * w)
    print(" 💡 Press [ESC] at any moment to safely break back to this screen.")
    print("=" * w)
    print(f"👉 Selection: {INPUT_BUFFER}", end="", flush=True)

def show_tuner_selection_menu():
    clear_terminal()
    w = min(get_terminal_width(), 70)
    print("=" * w)
    print(" 🎸 TARGET TUNER WORKBENCH: SELECT YOUR AIM".center(w)[:w])
    print("=" * w)
    for k, v in sorted(TUNING_PRESETS.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 999):
        print(f" [{k:<2}]  {v[0]:18} ──► ({', '.join(v[1])})")
    print("-" * w)
    print(f"👉 Choose tuning matrix ID to mount dashboard tracker: {INPUT_BUFFER}", end="", flush=True)

def draw_live_tuning_matrix_dashboard():
    clear_terminal()
    w = min(get_terminal_width(), 75)
    tuning_name, tuning_notes = TUNING_PRESETS.get(TARGET_TUNING_KEY, ("STANDARD", ["E2","A2","D3","G3","B3","E4"]))
    print("=" * w)
    print(f" 🎯 LIVE TARGET TRACKER WORKBENCH: {tuning_name}".center(w)[:w])
    print("=" * w)
    print(f" {'STRING':<10} │ {'TARGET NOTE':<15} │ {'TARGET FREQUENCY':<20} │ {'LIVE VARIANCE'}")
    print("─" * w)
    for reverse_idx, note_name in enumerate(reversed(tuning_notes)):
        string_num = 1 + reverse_idx
        target_hz = note_to_hz(note_name)
        variance_str = "------"
        if LIVE_TRACKED_PITCH > 0.0:
            note_only = note_name[:-1]
            live_only = LIVE_TRACKED_NOTE[:-1] if LIVE_TRACKED_NOTE else ""
            if note_only == live_only or (abs(LIVE_TRACKED_PITCH - target_hz) < 15.0):
                diff = LIVE_TRACKED_PITCH - target_hz
                if abs(diff) < 0.5: variance_str = "🟢 IN TUNE (0.0 Hz)"
                elif diff > 0: variance_str = f"🔺 SHARP (+{diff:.1f} Hz)"
                else: variance_str = f"🔹 FLAT ({diff:.1f} Hz)"
        print(f" String #{string_num:<3} │ {note_name:<15} │ {target_hz:<18.2f} Hz │ {variance_str}")
    print("=" * w)
    print(f" 🔊 Current Detected Input: {LIVE_TRACKED_NOTE if LIVE_TRACKED_NOTE else 'None':5} ({LIVE_TRACKED_PITCH:.1f} Hz)")
    print(" 👉 Press [ESC] to detach workbench and return to the main dashboard menu.")
    print("=" * w)

def show_layouts_menu():
    clear_terminal()
    w = min(get_terminal_width(), 70)
    layouts = [os.path.splitext(f)[0] for f in os.listdir(LAYOUTS_DIR) if f.endswith(".json")]
    print("=" * w)
    print(" 📂 USER KEYBOARD LAYOUT PROFILES ARCHIVE".center(w)[:w])
    print("=" * w)
    idx = 1
    for l in layouts:
        marker = "⭐ " if l == ACTIVE_LAYOUT_NAME else "   "
        print(f" [{idx}] {marker}{l}")
        idx += 1
    print("-" * w)
    print(f" [{idx}] ➕ [Create New Custom Layout Profile]")
    print("=" * w)
    print(f"👉 Selection: {INPUT_BUFFER}", end="", flush=True)

def show_tabs_archive_menu():
    clear_terminal()
    w = min(get_terminal_width(), 70)
    tab_files = sorted([f for f in os.listdir(TABS_DIR) if f.endswith(".txt")] if os.path.exists(TABS_DIR) else [])
    print("=" * w)
    print(" 📖 DIGITAL GUITAR TABLATURE REPOSITORY".center(w)[:w])
    print("=" * w)
    if not tab_files:
        print(" [No tablature text sheets identified inside ./tabs/]")
    else:
        for idx, filename in enumerate(tab_files, 1):
            clean_name = filename.replace(".txt", "").replace("_", " ").title()
            print(f" [{idx}]  🎼 {clean_name}")
    print("-" * w)
    print(" 💡 Put regular .txt tab files with 'TUNING: 1' inside ./tabs/ to load them.")
    print("=" * w)
    print(f"👉 Selection: {INPUT_BUFFER}", end="", flush=True)

def parse_and_load_tab_file(filename):
    path = os.path.join(TABS_DIR, filename)
    tuning_id = "1"
    content_lines = []
    if os.path.exists(path):
        with open(path, "r") as f:
            for line in f:
                strip_line = line.strip()
                if strip_line.upper().startswith("TUNING:"):
                    parts = strip_line.split(":")
                    if len(parts) > 1: tuning_id = parts[1].strip()
                else:
                    content_lines.append(line.rstrip('\n'))
    return {"tuning": tuning_id, "content": content_lines}

def draw_tab_player_screen():
    clear_terminal()
    w = min(get_terminal_width(), 80)
    clean_title = SELECTED_TAB_FILE_NAME.replace(".txt", "").replace("_", " ").title()
    tuning_key = LOADED_TAB_DATA["tuning"]
    tuning_name = TUNING_PRESETS.get(tuning_key, ("UNKNOWN", []))[0]
    print("=" * w)
    print(f" 🎼 PLAYING: {clean_title} ({tuning_name} TUNING)".center(w)[:w])
    print("=" * w)
    for line in LOADED_TAB_DATA["content"]:
        print(line[:w])
    print("=" * w)
    print(" options: [ESC] Close Song Viewer and Return to Archive")
    print("=" * w)

def draw_tab_recorder_gui():
    clear_terminal()
    w = min(get_terminal_width(), 80)
    tuning_name = TUNING_PRESETS.get(RECORDING_TUNING_KEY, ("STANDARD", []))[0]
    string_headers = ["e|", "B|", "G|", "D|", "A|", "E|"]
    if RECORDING_TUNING_KEY in TUNING_PRESETS:
        raw_notes = TUNING_PRESETS[RECORDING_TUNING_KEY][1]
        string_headers = [f"{n[:-1]}|" for n in reversed(raw_notes)]
    print("=" * w)
    print(f" 🎙️ LIVE AUDIO TAB CREATOR MODULE | TUNING: {tuning_name}".center(w)[:w])
    print("=" * w)
    print(" 💡 PLUCK NOTES ON YOUR GUITAR TO AUTO-WRITE FRETS INTO THE MATRIX.")
    print(" 💡 CHOOSE MODIFIERS SUB-OPTIONS VIA KEYBOARD BEFORE OR DURING SELECTIONS:")
    print("    [H] Hammer-on   [P] Pull-off   [S] Slide   [N] Natural Harmonic  [SPACE] Rest/Gap")
    print("    [Z] Undo Last   [W] Export File to Disk")
    print("=" * w)
    max_cols = w - 8
    matrix_length = len(RECORDED_TAB_MATRIX[0])
    start_idx = max(0, matrix_length - max_cols)
    for s_idx in range(6):
        row_slice = RECORDED_TAB_MATRIX[s_idx][start_idx:]
        row_str = "".join(row_slice)
        print(f" {string_headers[s_idx]}-{row_str}")
    print("=" * w)
    active_mods = ", ".join(MODIFIER_QUEUE) if MODIFIER_QUEUE else "None (Regular Note)"
    print(f" ⚡ Queued Technique Modifier: [{active_mods}]")
    print(" 👉 Press [ESC] to abort and return to Hub Main Menu.")
    print("=" * w)

def append_element_to_tab_matrix(target_string, character_symbol):
    for s_idx in range(6):
        if s_idx == target_string: RECORDED_TAB_MATRIX[s_idx].append(str(character_symbol))
        else: RECORDED_TAB_MATRIX[s_idx].append("-" * len(str(character_symbol)))

def insert_rest_gap():
    for s_idx in range(6): RECORDED_TAB_MATRIX[s_idx].append("-")

def undo_last_tab_matrix_column():
    for s_idx in range(6):
        if RECORDED_TAB_MATRIX[s_idx]: RECORDED_TAB_MATRIX[s_idx].pop()

def match_pitch_to_closest_string_and_fret(pitch_hz):
    midi_num = round(12 * np.log2(pitch_hz / (440 * pow(2, -4.75))))
    tuning_notes = TUNING_PRESETS.get(RECORDING_TUNING_KEY, ("STANDARD", ["E2", "A2", "D3", "G3", "B3", "E4"]))[1]
    best_string_idx = None
    best_fret = None
    min_fret_distance = 999
    for s_idx in range(6):
        string_note = tuning_notes[s_idx]
        base_midi = note_to_midi(string_note)
        fret = midi_num - base_midi
        if 0 <= fret <= 24:
            if fret < min_fret_distance:
                min_fret_distance = fret
                best_string_idx = 5 - s_idx
                best_fret = fret
    return best_string_idx, best_fret, midi_num

def show_tunings_menu():
    clear_terminal()
    w = min(get_terminal_width(), 70)
    print("=" * w)
    print(" 🎸 INSTRUMENT TUNING SCHEMATICS MANAGER".center(w)[:w])
    print("=" * w)
    for k, v in sorted(TUNING_PRESETS.items(), key=lambda x: int(x[0]) if x[0].isdigit() else 999):
        print(f" [{k:<2}]  {v[0]:18} ──► ({', '.join(v[1])})")
    print("-" * w)
    print(" [A]  ➕ Create/Register a New Custom Guitar Tuning Profile")
    print(" [ESC] Return to System Dashboard Hub")
    print("=" * w)
    print(f"👉 Selection: {INPUT_BUFFER}", end="", flush=True)

def show_settings_menu():
    clear_terminal()
    w = min(get_terminal_width(), 70)
    print("=" * w)
    print(" ⚙️ SYSTEM SETTINGS CONFIGURATION".center(w)[:w])
    print("=" * w)
    current_name = "None Specified"
    if DEVICE_INDEX is not None:
        try: current_name = sd.query_devices(DEVICE_INDEX)['name']
        except Exception: current_name = f"Index #{DEVICE_INDEX}"
    print(f" [1] Audio Input Endpoint Selection")
    print(f"     Active Endpoint -> Index #{DEVICE_INDEX}: {current_name}")
    print("-" * w)
    print(" 💡 Press [ESC] to safely return to Main Menu.")
    print("=" * w)
    print(f"👉 Selection: {INPUT_BUFFER}", end="", flush=True)

def draw_fretboard_matrix(layout_name, layout_data):
    clear_terminal()
    tuning_key = layout_data.get("tuning", "1")
    tuning_name = TUNING_PRESETS.get(tuning_key, ("STANDARD", []))[0]
    max_frets = layout_data.get("max_frets", 15)
    mappings = layout_data.get("mappings", {})
    fret_notes = get_fretboard_notes(tuning_key, max_frets)
    cell_w = 6
    divider_len = 10 + ((max_frets + 1) * cell_w)
    print("=" * divider_len)
    print(f" 🎛 Levant Fretboard: {layout_name.upper()} ({tuning_name} | {max_frets} FRETS)")
    print("=" * divider_len)
    print("Str │ " + "".join(f" F{i:<2} │" for i in range(max_frets + 1)))
    print("────┼─" + "─────┼─" * max_frets + "────┼")
    for s_idx in reversed(range(6)):
        row_str = f" S{s_idx+1} │ "
        for f_idx in range(max_frets + 1):
            note_name = fret_notes[s_idx][f_idx]
            if note_name in mappings:
                char_val = mappings[note_name]
                if char_val == "space": disp = "SPC"
                elif char_val == "backspace": disp = "BCK"
                elif char_val == "tab": disp = "TAB"
                elif char_val == "enter": disp = "ENT"
                else: disp = f"'{char_val}'"[:3]
                row_str += f" {disp:<3} │"
            else: row_str += "  ?   │"
        print(row_str)
    print("=" * divider_len)
    print(" Options: [A] Activate Profile  │  [M] Modify Mappings  │  [F] Resize Frets  │  [ESC] Return")
    print("=" * divider_len)
    print(f"👉 Selection: {INPUT_BUFFER}", end="", flush=True)

# ========================================================
# 4. MASTER WIZARD RENDER SCHEMATICS (DATA ENTRY PROTECTION)
# ========================================================
def render_wizard_state():
    clear_terminal()
    w = min(get_terminal_width(), 70)
    print("=" * w)
    
    if CURRENT_STATE == "WIZARD_CREATE_TUNING":
        print(" ➕ WIZARD: REGISTER CUSTOM INSTRUMENT TUNING".center(w)[:w])
        print("=" * w)
        if WIZARD_STAGE == 6:
            print(" STEP 1: Enter a clean name for your Custom Tuning Profile")
            print(" Example: DROP C, BALKAN, MY_TUNING")
            print("-" * w)
            print(f" Current Input: {WIZARD_DATA.get('name', '')}")
        else:
            string_num = 6 - WIZARD_STAGE
            print(f" STEP 2: Map absolute pitch target for Guitar String #{string_num}")
            print(" Expected formatting pattern: [Note Letter] + [Octave Number] (e.g., D2, G2)")
            print("-" * w)
            print(f" Registered String Pitch Array: {WIZARD_DATA.get('notes', [])}")
            
    elif CURRENT_STATE == "WIZARD_CREATE_LAYOUT":
        print(" ➕ WIZARD: CREATE CUSTOM KEYBOARD CODES MATRIX".center(w)[:w])
        print("=" * w)
        if WIZARD_STAGE == 0:
            print(" STEP 1: Define alphanumeric profile moniker:")
        elif WIZARD_STAGE == 1:
            print(" STEP 2: Link target underlying tuning preset matrix system ID:")
        elif WIZARD_STAGE == 2:
            print(" STEP 3: Assign max virtual fret columns count (Limit: 1-36):")
            
    elif CURRENT_STATE == "WIZARD_MODIFY_MAPPING":
        print(" 🛠️  WIZARD: BIND INDIVIDUAL CODE TRIGGER INTERCEPT".center(w)[:w])
        print("=" * w)
        if WIZARD_STAGE == 0:
            print(" STEP 1: Target physical structural string row tracking number (1-6):")
        elif WIZARD_STAGE == 1:
            print(f" STEP 2: Target fretboard coordinate index column (0-{WIZARD_DATA.get('max_frets', 22)}):")
        elif WIZARD_STAGE == 2:
            print(f" STEP 3: Define string value to send when Note [{WIZARD_DATA.get('note', '')}] sounds:")
            print(" (Leave blank/empty and press Enter to scrub existing binding clean)")
            
    elif CURRENT_STATE == "WIZARD_RESIZE_FRETS":
        print(" 📐 WIZARD: CALIBRATE PHYSICAL MAX FRET BOUNDARIES".center(w)[:w])
        print("=" * w)
        print(" Input new structural max fret division limit (Range: 1-36):")
        
    elif CURRENT_STATE == "WIZARD_EXPORT_TAB":
        print(" 💾 WIZARD: EXPORT GENERATED SHEET MATRIX TO STORAGE".center(w)[:w])
        print("=" * w)
        print(" Input file identifier name descriptor to write to local directory:")
        
    elif CURRENT_STATE == "WIZARD_SET_AUDIO":
        print(" 🎤 WIZARD: RE-ROUTE LIVE CAPTURE AUDIO HARDWARE LINK".center(w)[:w])
        print("=" * w)
        devices = sd.query_devices()
        for idx, dev in enumerate(devices):
            if dev['max_input_channels'] > 0:
                print(f" [{idx}]  Input Device Connection Point -> {dev['name']}")
        print("-" * w)
        print(" Type preferred valid endpoint hardware index number sequence below:")
        
    print("-" * w)
    print(f"👉 Input: {INPUT_BUFFER}", end="", flush=True)

def refresh_current_menu_ui():
    if CURRENT_STATE == "MENU": show_main_menu()
    elif CURRENT_STATE == "TUNER_SELECT": show_tuner_selection_menu()
    elif CURRENT_STATE == "LAYOUTS_MENU": show_layouts_menu()
    elif CURRENT_STATE == "TABS_MENU": show_tabs_archive_menu()
    elif CURRENT_STATE == "TUNINGS_MENU": show_tunings_menu()
    elif CURRENT_STATE == "SETTINGS_MENU": show_settings_menu()
    elif CURRENT_STATE == "VIEW_LAYOUT": draw_fretboard_matrix(SELECTED_LAYOUT_TO_VIEW, load_layout_file(SELECTED_LAYOUT_TO_VIEW))
    elif CURRENT_STATE.startswith("WIZARD_"): render_wizard_state()

# ========================================================
# ASYNCHRONOUS DESKTOP INTERCEPT EVENT EVENT-LOOP
# ========================================================
def on_press(key):
    global CURRENT_STATE, ACTIVE_LAYOUT_NAME, NOTE_MAPPING, SELECTED_LAYOUT_TO_VIEW, CURRENT_LAYOUT_DATA
    global SELECTED_TAB_FILE_NAME, LOADED_TAB_DATA, INPUT_BUFFER, WIZARD_STAGE, WIZARD_DATA, TARGET_TUNING_KEY
    global RECORDING_TUNING_KEY, RECORDED_TAB_MATRIX, MODIFIER_QUEUE, DEVICE_INDEX

    if key == pynput_keyboard.Key.esc:
        INPUT_BUFFER = ""
        purge_input_buffer()
        if CURRENT_STATE in ["WIZARD_CREATE_TUNING", "WIZARD_CREATE_LAYOUT", "VIEW_LAYOUT"]:
            CURRENT_STATE = "LAYOUTS_MENU"
            show_layouts_menu()
        elif CURRENT_STATE in ["WIZARD_MODIFY_MAPPING", "WIZARD_RESIZE_FRETS"]:
            CURRENT_STATE = "VIEW_LAYOUT"
            draw_fretboard_matrix(SELECTED_LAYOUT_TO_VIEW, load_layout_file(SELECTED_LAYOUT_TO_VIEW))
        elif CURRENT_STATE in ["WIZARD_EXPORT_TAB", "TAB_RECORD", "TUNER_TRACKING", "TUNER_SELECT", "TUNINGS_MENU"]:
            CURRENT_STATE = "MENU"
            show_main_menu()
        elif CURRENT_STATE == "VIEW_TAB":
            CURRENT_STATE = "TABS_MENU"
            show_tabs_archive_menu()
        else:
            CURRENT_STATE = "MENU"
            show_main_menu()
        return

    # SKIP BUFFER CAPTURE IN LIVE INTERCEPT MODES
    if CURRENT_STATE in ["IDE", "TAB_RECORD", "VIEW_TAB", "TUNER_TRACKING"]:
        if CURRENT_STATE == "TAB_RECORD" and hasattr(key, 'char'):
            cmd = key.char.lower()
            if cmd in ['h', 'p', 's', 'n']:
                MODIFIER_QUEUE.append(cmd)
                draw_tab_recorder_gui()
            elif cmd == 'z':
                undo_last_tab_matrix_column()
                draw_tab_recorder_gui()
            elif cmd == 'w':
                CURRENT_STATE = "WIZARD_EXPORT_TAB"
                WIZARD_STAGE = 0
                render_wizard_state()
        elif CURRENT_STATE == "TAB_RECORD" and key == pynput_keyboard.Key.space:
            insert_rest_gap()
            draw_tab_recorder_gui()
        return

    # UNIFIED BUFFER INGESTION FOR ALL MENUS AND WIZARDS
    if hasattr(key, 'char') and key.char is not None:
        INPUT_BUFFER += key.char
        refresh_current_menu_ui()
    elif key == pynput_keyboard.Key.space:
        INPUT_BUFFER += " "
        refresh_current_menu_ui()
    elif key == pynput_keyboard.Key.backspace:
        INPUT_BUFFER = INPUT_BUFFER[:-1]
        refresh_current_menu_ui()
    elif key == pynput_keyboard.Key.enter:
        cleaned_input = INPUT_BUFFER.strip()
        INPUT_BUFFER = ""
        
        # PROTECTION GUARD: Instantly dump any hidden terminal echo backlogs before routing
        purge_input_buffer()
        
        # ---------------- PAGE-LEVEL MENUS DISPATCH ----------------
        if CURRENT_STATE == "MENU":
            if cleaned_input == "1":
                CURRENT_STATE = "IDE"
                clear_terminal()
                print("🏁 Pentatonic Execution Framework Active.")
                print(f"⌨️  Active Profile Layout Configuration: [{ACTIVE_LAYOUT_NAME}]")
                print("👉 Press [ESC] at any time to open the Main Menu.")
                print("-" * 60)
            elif cleaned_input == "2":
                CURRENT_STATE = "TUNER_SELECT"
                show_tuner_selection_menu()
            elif cleaned_input == "3":
                CURRENT_STATE = "LAYOUTS_MENU"
                show_layouts_menu()
            elif cleaned_input == "4":
                CURRENT_STATE = "TABS_MENU"
                show_tabs_archive_menu()
            elif cleaned_input == "5":
                RECORDED_TAB_MATRIX = [[] for _ in range(6)]
                MODIFIER_QUEUE = []
                CURRENT_STATE = "TAB_RECORD"
                draw_tab_recorder_gui()
            elif cleaned_input == "6":
                CURRENT_STATE = "TUNINGS_MENU"
                show_tunings_menu()
            elif cleaned_input == "7":
                CURRENT_STATE = "SETTINGS_MENU"
                show_settings_menu()
            elif cleaned_input == "8":
                print("\nGoodbye!")
                silence_terminal_echo(disable=False)
                purge_input_buffer()
                os._exit(0)
            else:
                show_main_menu()

        elif CURRENT_STATE == "TUNER_SELECT":
            if cleaned_input in TUNING_PRESETS:
                TARGET_TUNING_KEY = cleaned_input
                CURRENT_STATE = "TUNER_TRACKING"
            else:
                CURRENT_STATE = "MENU"
                show_main_menu()

        elif CURRENT_STATE == "TUNINGS_MENU":
            if cleaned_input.lower() == 'a':
                CURRENT_STATE = "WIZARD_CREATE_TUNING"
                WIZARD_STAGE = 6
                WIZARD_DATA = {}
                render_wizard_state()
            else:
                show_tunings_menu()

        elif CURRENT_STATE == "SETTINGS_MENU":
            if cleaned_input == "1":
                CURRENT_STATE = "WIZARD_SET_AUDIO"
                WIZARD_STAGE = 0
                render_wizard_state()
            else:
                show_settings_menu()

        elif CURRENT_STATE == "TABS_MENU":
            tab_files = sorted([f for f in os.listdir(TABS_DIR) if f.endswith(".txt")] if os.path.exists(TABS_DIR) else [])
            try:
                val = int(cleaned_input)
                if 1 <= val <= len(tab_files):
                    SELECTED_TAB_FILE_NAME = tab_files[val - 1]
                    LOADED_TAB_DATA = parse_and_load_tab_file(SELECTED_TAB_FILE_NAME)
                    CURRENT_STATE = "VIEW_TAB"
                    draw_tab_player_screen()
                else: show_tabs_archive_menu()
            except ValueError:
                show_tabs_archive_menu()

        elif CURRENT_STATE == "LAYOUTS_MENU":
            layouts = [os.path.splitext(f)[0] for f in os.listdir(LAYOUTS_DIR) if f.endswith(".json")]
            try:
                val = int(cleaned_input)
                if 1 <= val <= len(layouts):
                    SELECTED_LAYOUT_TO_VIEW = layouts[val - 1]
                    CURRENT_STATE = "VIEW_LAYOUT"
                    draw_fretboard_matrix(SELECTED_LAYOUT_TO_VIEW, load_layout_file(SELECTED_LAYOUT_TO_VIEW))
                elif val == len(layouts) + 1:
                    CURRENT_STATE = "WIZARD_CREATE_LAYOUT"
                    WIZARD_STAGE = 0
                    WIZARD_DATA = {}
                    render_wizard_state()
                else: show_layouts_menu()
            except ValueError:
                show_layouts_menu()
                
        elif CURRENT_STATE == "VIEW_LAYOUT":
            cmd = cleaned_input.lower()
            viewing_data = load_layout_file(SELECTED_LAYOUT_TO_VIEW)
            if cmd == 'a':
                ACTIVE_LAYOUT_NAME = SELECTED_LAYOUT_TO_VIEW
                CURRENT_LAYOUT_DATA = viewing_data
                NOTE_MAPPING = get_parsed_runtime_mappings(CURRENT_LAYOUT_DATA)
                save_last_used_layout_name(ACTIVE_LAYOUT_NAME)
                CURRENT_STATE = "LAYOUTS_MENU"
                show_layouts_menu()
            elif cmd == 'm':
                CURRENT_STATE = "WIZARD_MODIFY_MAPPING"
                WIZARD_STAGE = 0
                WIZARD_DATA = {}
                render_wizard_state()
            elif cmd == 'f':
                CURRENT_STATE = "WIZARD_RESIZE_FRETS"
                WIZARD_STAGE = 0
                render_wizard_state()
            else:
                draw_fretboard_matrix(SELECTED_LAYOUT_TO_VIEW, viewing_data)

        # ---------------- DATA-ENTRY WIZARDS DISPATCH ----------------
        elif CURRENT_STATE == "WIZARD_CREATE_TUNING":
            if WIZARD_STAGE == 6:
                WIZARD_DATA["name"] = cleaned_input.upper() if cleaned_input else "CUSTOM_TUNING"
                WIZARD_DATA["notes"] = []
                WIZARD_STAGE = 5
                render_wizard_state()
            else:
                if len(cleaned_input) >= 2 and cleaned_input[-1].isdigit() and cleaned_input[0] in "ABCDEFG":
                    WIZARD_DATA["notes"].append(cleaned_input.upper())
                    WIZARD_STAGE -= 1
                    if WIZARD_STAGE < 0:
                        existing = [int(k) for k in TUNING_PRESETS.keys() if k.isdigit()]
                        next_id = max(existing) + 1 if existing else 1
                        filename = f"{str(next_id).zfill(2)}_{WIZARD_DATA['name'].lower().replace(' ', '_')}.json"
                        WIZARD_DATA["notes"].reverse()
                        with open(os.path.join(TUNINGS_DIR, filename), "w") as f:
                            json.dump({"name": WIZARD_DATA["name"], "notes": WIZARD_DATA["notes"]}, f, indent=4)
                        load_all_tunings()
                        CURRENT_STATE = "TUNINGS_MENU"
                        show_tunings_menu()
                    else: render_wizard_state()
                else: render_wizard_state()

        elif CURRENT_STATE == "WIZARD_CREATE_LAYOUT":
            if WIZARD_STAGE == 0:
                WIZARD_DATA["name"] = cleaned_input.lower().replace(" ", "_") if cleaned_input else "new_guitar_layout"
                WIZARD_STAGE = 1
                render_wizard_state()
            elif WIZARD_STAGE == 1:
                WIZARD_DATA["tuning"] = cleaned_input if cleaned_input in TUNING_PRESETS else "1"
                WIZARD_STAGE = 2
                render_wizard_state()
            elif WIZARD_STAGE == 2:
                try: frets = int(cleaned_input)
                except ValueError: frets = 22
                new_struct = {"tuning": WIZARD_DATA["tuning"], "max_frets": frets, "mappings": {}}
                if WIZARD_DATA["name"] == "chromatic_maximalist":
                    new_struct["mappings"] = generate_maximalist_mappings(WIZARD_DATA["tuning"], frets)
                save_layout_file(WIZARD_DATA["name"], new_struct)
                SELECTED_LAYOUT_TO_VIEW = WIZARD_DATA["name"]
                CURRENT_STATE = "VIEW_LAYOUT"
                draw_fretboard_matrix(SELECTED_LAYOUT_TO_VIEW, new_struct)

        elif CURRENT_STATE == "WIZARD_MODIFY_MAPPING":
            viewing_data = load_layout_file(SELECTED_LAYOUT_TO_VIEW)
            if WIZARD_STAGE == 0:
                try:
                    val = int(cleaned_input)
                    if 1 <= val <= 6:
                        WIZARD_DATA["string"] = val
                        WIZARD_DATA["max_frets"] = viewing_data.get("max_frets", 22)
                        WIZARD_STAGE = 1
                except ValueError: pass
                render_wizard_state()
            elif WIZARD_STAGE == 1:
                try:
                    val = int(cleaned_input)
                    if 0 <= val <= WIZARD_DATA["max_frets"]:
                        WIZARD_DATA["fret"] = val
                        s_idx = 6 - WIZARD_DATA["string"]
                        fret_notes = get_fretboard_notes(viewing_data.get("tuning", "1"), WIZARD_DATA["max_frets"])
                        WIZARD_DATA["note"] = fret_notes[s_idx][val]
                        WIZARD_STAGE = 2
                except ValueError: pass
                render_wizard_state()
            elif WIZARD_STAGE == 2:
                if not cleaned_input:
                    if WIZARD_DATA["note"] in viewing_data["mappings"]: del viewing_data["mappings"][WIZARD_DATA["note"]]
                else: viewing_data["mappings"][WIZARD_DATA["note"]] = cleaned_input
                save_layout_file(SELECTED_LAYOUT_TO_VIEW, viewing_data)
                if SELECTED_LAYOUT_TO_VIEW == ACTIVE_LAYOUT_NAME:
                    CURRENT_LAYOUT_DATA = viewing_data
                    NOTE_MAPPING = get_parsed_runtime_mappings(CURRENT_LAYOUT_DATA)
                CURRENT_STATE = "VIEW_LAYOUT"
                draw_fretboard_matrix(SELECTED_LAYOUT_TO_VIEW, viewing_data)

        elif CURRENT_STATE == "WIZARD_RESIZE_FRETS":
            try:
                frets = int(cleaned_input)
                if 1 <= frets <= 36:
                    layout_data = load_layout_file(SELECTED_LAYOUT_TO_VIEW)
                    layout_data["max_frets"] = frets
                    save_layout_file(SELECTED_LAYOUT_TO_VIEW, layout_data)
            except ValueError: pass
            CURRENT_STATE = "VIEW_LAYOUT"
            draw_fretboard_matrix(SELECTED_LAYOUT_TO_VIEW, load_layout_file(SELECTED_LAYOUT_TO_VIEW))

        elif CURRENT_STATE == "WIZARD_EXPORT_TAB":
            name = cleaned_input.lower().replace(" ", "_") if cleaned_input else "recorded_guitar_riff"
            path = os.path.join(TABS_DIR, f"{name}.txt")
            raw_notes = TUNING_PRESETS[RECORDING_TUNING_KEY][1]
            string_headers = [f"{n[:-1]}|" for n in reversed(raw_notes)]
            try:
                with open(path, "w") as f:
                    f.write(f"TUNING: {RECORDING_TUNING_KEY}\n")
                    f.write(f"--- EXPORTED TAB: {name.upper()} ---\n\n")
                    for s_idx in range(6): f.write(f"{string_headers[s_idx]}-{''.join(RECORDED_TAB_MATRIX[s_idx])}\n")
            except Exception: pass
            CURRENT_STATE = "MENU"
            show_main_menu()

        elif CURRENT_STATE == "WIZARD_SET_AUDIO":
            try:
                val = int(cleaned_input)
                devices = sd.query_devices()
                if 0 <= val < len(devices) and devices[val]['max_input_channels'] > 0:
                    DEVICE_INDEX = val
                    SETTINGS["device_index"] = DEVICE_INDEX
                    save_settings(SETTINGS)
                    restart_audio_stream()
            except ValueError: pass
            CURRENT_STATE = "SETTINGS_MENU"
            show_settings_menu()

listener = pynput_keyboard.Listener(on_press=on_press)
listener.start()

def audio_callback(indata, frames, time_info, status):
    audio_queue.put(indata[:, 0].copy())

# ========================================================
# DIGITAL PROCESSING SIGNAL PIPELINE & PARSING ENGINE
# ========================================================
def process_audio():
    global last_strike_time, current_active_note, previous_volume
    global LAST_DETECTED_MIDI, LAST_DETECTED_STRING, LAST_DETECTED_FRET
    global LIVE_TRACKED_PITCH, LIVE_TRACKED_NOTE
    
    last_ui_update = 0.0
    
    while True:
        new_chunk = audio_queue.get()
        current_time = time.time()
        current_volume = np.max(np.abs(new_chunk))
        
        if CURRENT_STATE not in ["IDE", "TUNER_TRACKING", "TAB_RECORD"]:
            LIVE_TRACKED_PITCH = 0.0
            LIVE_TRACKED_NOTE = ""
            previous_volume = current_volume
            continue
            
        signal = new_chunk.astype(np.float32)
        pitch = pitch_detector(signal)[0]
        
        if pitch <= 0 or current_volume < 0.020:
            current_active_note = None  
            LIVE_TRACKED_PITCH = 0.0
            LIVE_TRACKED_NOTE = ""
            if CURRENT_STATE == "TUNER_TRACKING" and (current_time - last_ui_update) > 0.25:
                draw_live_tuning_matrix_dashboard()
                last_ui_update = current_time
            previous_volume = current_volume
            continue
            
        note = hz_to_note_name(pitch)
        
        if CURRENT_STATE == "TUNER_TRACKING":
            LIVE_TRACKED_PITCH = pitch
            LIVE_TRACKED_NOTE = note
            if (current_time - last_ui_update) > 0.15:
                draw_live_tuning_matrix_dashboard()
                last_ui_update = current_time
            previous_volume = current_volume
            continue
            
        if CURRENT_STATE == "TAB_RECORD":
            if (current_time - last_strike_time) < INITIAL_STRIKE_CAGE:
                previous_volume = current_volume
                continue
                
            s_idx, fret, midi_num = match_pitch_to_closest_string_and_fret(pitch)
            if s_idx is None:
                previous_volume = current_volume
                continue
                
            is_fluid_transition = False
            if LAST_DETECTED_MIDI is not None and (current_time - last_strike_time) < 0.450:
                if midi_num != LAST_DETECTED_MIDI and current_volume < (previous_volume * 1.10):
                    is_fluid_transition = True
            
            if is_fluid_transition and not MODIFIER_QUEUE:
                if s_idx == LAST_DETECTED_STRING:
                    if abs(midi_num - LAST_DETECTED_MIDI) >= 2: MODIFIER_QUEUE.append("s")
                    else: MODIFIER_QUEUE.append("h" if midi_num > LAST_DETECTED_MIDI else "p")

            fret_symbol = str(fret)
            if MODIFIER_QUEUE:
                mod = MODIFIER_QUEUE.pop(0)
                if mod == "n": fret_symbol = f"<{fret}>"
                else: fret_symbol = f"{mod}{fret}"
            
            append_element_to_tab_matrix(s_idx, fret_symbol)
            LAST_DETECTED_MIDI = midi_num
            LAST_DETECTED_STRING = s_idx
            LAST_DETECTED_FRET = fret
            last_strike_time = current_time
            draw_tab_recorder_gui()
            with audio_queue.mutex: audio_queue.queue.clear()
            previous_volume = current_volume
            continue

        if CURRENT_STATE == "IDE":
            if (current_time - last_strike_time) < INITIAL_STRIKE_CAGE:
                previous_volume = current_volume
                continue  
            if note == current_active_note:
                required_ratio = LOW_E_SPIKE_RATIO if note in ["E1", "E2"] else DEFAULT_SPIKE_RATIO
                if current_volume < (previous_volume * required_ratio):
                    previous_volume = current_volume
                    continue  
            if note in NOTE_MAPPING:
                target_key = NOTE_MAPPING[note]
                print(f"🎯 Match: {note:4} -> ⌨️ {str(target_key)}")
                keyboard_controller.press(target_key)
                keyboard_controller.release(target_key)
                current_active_note = note
                last_strike_time = time.time()
                time.sleep(OUTPUT_PAUSE_MS)
                with audio_queue.mutex: audio_queue.queue.clear()
            previous_volume = current_volume

def hz_to_note_name(hz):
    if hz < 20: return None
    A4 = 440
    C0 = A4 * pow(2, -4.75)
    h = round(12 * np.log2(hz / C0))
    return f"{NOTE_NAMES[h % 12]}{h // 12}"

worker = threading.Thread(target=process_audio, daemon=True)
worker.start()

def start_audio_stream():
    global audio_stream, DEVICE_INDEX
    if DEVICE_INDEX is None: return False
    try:
        device_info = sd.query_devices(DEVICE_INDEX, 'input')
        max_input_channels = int(device_info.get('max_input_channels', 1))
        runtime_channels = min(2, max_input_channels) if max_input_channels > 0 else 1
        audio_stream = sd.InputStream(device=DEVICE_INDEX, channels=runtime_channels, callback=audio_callback, blocksize=HOP_SIZE, samplerate=SAMPLE_RATE)
        audio_stream.start()
        return True
    except Exception: return False

def restart_audio_stream():
    global audio_stream
    if audio_stream is not None:
        try:
            audio_stream.stop()
            audio_stream.close()
        except Exception: pass
    with audio_queue.mutex: audio_queue.queue.clear()
    start_audio_stream()

# ========================================================
# 5. CORE EXECUTION WRAPPER & RUNTIME INITIALIZATION
# ========================================================
try:
    # Silence the terminal echo before printing out the main interface loop
    silence_terminal_echo(disable=True)
    purge_input_buffer()
    
    start_audio_stream()
    show_main_menu()

    while True: 
        sd.sleep(1000)

except KeyboardInterrupt:
    pass
finally:
    # Ensure standard terminal properties are fully returned back to the shell environment
    silence_terminal_echo(disable=False)
    purge_input_buffer()
    print("\n[!] Terminal state clean. Goodbye!")
    os._exit(0)
