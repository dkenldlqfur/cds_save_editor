# Windows XP edition

This branch is a source port for **Windows XP SP3 (32-bit)**.  It targets
Python 3.4 x86, which is the final CPython series that can be used for this
purpose.  The normal `main` branch remains the modern Windows build.

## Deliberate limitations

- The GitHub self-updater is disabled.  An XP build must never replace itself
  with the normal, Windows 10+ executable.
- Discovery and ship videos use a reduced VLC 3.0.21 XP runtime.  Keep the
  bundled `Resources\vlc` directory and its selected plugins together.
- The navigation map requires the bundled Pillow 5.4.1 runtime.  Ordinary
  image previews still retain the editor's Tk-compatible fallback.

## Reproducible build environment

Use a Windows XP SP3 32-bit virtual machine (recommended) or a 32-bit Python
3.4 build environment.  Install only compatible package versions:

```bat
python -m pip install "pyinstaller==3.3.1" "Pillow==5.4.1" "python-vlc==3.0.11115"
python -m PyInstaller --noconfirm --clean CDS_SaveEditor_xp.spec
```

The resulting `dist\CDS_SaveEditor_XP_v1.2.2` directory must be copied or zipped
as a whole and smoke-tested on a real XP SP3 installation.  Building the
executable on a newer Windows system does not substitute for that test.

## Version 1.2.2 port

- Includes the 1.2.1 city trade layout, common goods, price tooltips, and
  clearing of stale images/values for cities without a trading post.
- Adds the current-city selector with an upward eight-row popup. Moving
  characters and characters without a city are read-only; unhireable
  characters do not show this row.
- Keeps keyboard focus on the city selector and excludes the read-only
  basic-information table from keyboard navigation.
- Loads common error messages from `Resources/data/error_messages.json`
  through a shared GUI-independent resource loader.
- Retains the XP notebook/spinbox shims, Pillow compatibility, reduced
  32-bit VLC runtime, and disabled self-updater.

Run the compatibility regression tests with the bundled interpreter:

```bat
.tools\Python34-x86\python.exe -m unittest discover -s tests -v
```
