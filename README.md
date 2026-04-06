# PlantUML Previewer

A simple split-view PlantUML editor and previewer built with PySide6.

## Features

- resizable split view
- live PNG preview rendered by the system-installed `plantuml`
- mouse wheel zoom in/out on the preview
- drag the preview with the mouse
- monospace editor font
- basic PlantUML syntax highlighting
- basic completion popup on `Ctrl+Space`
- accept completion with `Enter`, `Return`, or `Tab`
- copy rendered image to clipboard with `Ctrl+Shift+C`

## Runtime dependency

This app expects a working `plantuml` command in your system `PATH`.

Check it with:

```bash
which plantuml
plantuml -version
```

Or override it:

```bash
export PLANTUML_CMD=/full/path/to/plantuml
```

## Development

```bash
./scripts/setup_venv.sh
source .venv/bin/activate
python app.py
```

## Packaging

```bash
./scripts/pack_single_file.sh
```

The output executable will be placed under `dist/plantuml_previewer`.


Additional notes:
- View -> 100% shows the image at actual pixel size.
- The preview now renders PNG at 192 DPI by default for cleaner downscaling.
- You can override it with `PLANTUML_DPI=144` or another value.
