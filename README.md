# 🎸 Guitar Pitch Keyboard Automation Engine

An asynchronous audio signal processing tool that translates real-time guitar pitch inputs (Hz) into readable alphanumeric keyboard events (MIDI). Features structural fretboard layout profiles, live target tuner tracking, and automated virtual environment setup with advanced terminal echo-suppression protections.

## 📋 System Requirements

### 1. Linux System Dependencies
Before running the Python script, your system needs ALSA/Jack audio headers and X11 automation libraries installed:
```bash
sudo apt update
sudo apt install python3-pip python3-venv libasound2-dev libjack-jackd2-dev libxtst-dev
```
### 2. Hardware Connectivity
* Audio Source: A guitar plugged into an interface (like a Line 6 / Spider amplifier via USB) mapped as an active input terminal configuration.

## 🚀 Getting Started

The script features an integrated bootstrap launcher that automatically handles virtual environment generation and package installation (numpy, sounddevice, aubio, pynput) on its first launch.

# Mark the script as executable
```bash
chmod +x guitar_control.py
```
# Launch the Hub UI directly
```bash
./guitar_control.py
```
