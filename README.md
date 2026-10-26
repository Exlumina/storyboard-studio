# Storyboard Studio

An offline, local storyboard editor for connecting scenes, timing, reference media, and feedback on a dark node canvas. Developed by Exlumina. Version 0.5.2.

## Start

Requires Python 3.11 or newer and a modern desktop browser. There are no Python packages, npm dependencies, accounts, or cloud services to install.

```sh
python3 scripts/launch_storyboard.py --project ./projects/My_Film --title "My film" --port 8840
```

Open the loopback URL printed by the launcher. It binds only to 127.0.0.1 and selects another free port if needed. Your boards, original imports, revisions, and receipts stay in that project folder. Keep projects outside the source checkout when possible, and back them up as ordinary private folders.

For a synthetic example with three described scenes and no proprietary media:

```sh
python3 scripts/create_example.py --project ./projects/Example
python3 scripts/launch_storyboard.py --project ./projects/Example --port 8840
```

Or run the launcher with `--init-only` to create a blank project without starting a service. Existing project data is preserved. A copied project retains its identity; use a new directory and initialization for an independent project.

## Work on a board

Create scenes, edit titles, descriptions, durations, framing intent, and feedback directly on their cards. Connect a Start marker through the intended scenes to an End marker; choose one path when experimenting with alternatives. The selected path controls the saved brief, while disconnected alternatives remain editable.

Use the reference library for local images and clips, switch or duplicate boards, save revisions, and export board JSON or a production brief. Mouse wheel zooms; trackpad gestures pan. Space plus drag pans the canvas. Keyboard shortcuts and navigation modes are described in the canvas label and menus.

The editor saves local board revisions. Keep backups before importing or restoring significant work. This is a single-user local service, without authentication or encryption; do not expose its port through a tunnel, reverse proxy, or public interface.

## Media and render handoff

Optional FFmpeg and ffprobe executables on PATH enable local media imports and bounded clip proxies. No FFmpeg binaries, fonts, external libraries, stock imagery, model assets, or proprietary media are bundled. Missing tools produce an actionable error; board authoring itself needs only Python and the browser.

Saving a request creates a local immutable brief for a separate production owner. **The launcher, editor, and handoff helpers never start a renderer or send a chat message automatically.** Reference imagery is visual guidance, not proof of native model or camera provenance. Native-return admission checks validate an explicit completion manifest, source hashes, scene/frame phases, and requested effects; a synthetic test receipt does not establish an actual render.

Generic helper CLIs are in `assets/storyboard-studio/`: `storyboard_reader.py`, `feedback_handoff.py`, `render_handoff.py`, and `storyboard_conformance.py`. Run each with `--help`. Point `--base` at your own printed loopback URL.

## Stop, resume, and refresh

The launch receipt in the project's `data/launch.json` records its exact PID, command, URL, and code hashes. Verify the process command and project path before stopping that specific server. The launcher reuses a service only after matching its identity and ownership. Do not stop an unrelated listener or change application files beneath a running server.

To refresh a project from a newer source checkout, stop its verified server first, then run the launcher with `--refresh-ui`. It backs up the replaced application files and preserves boards, history, imports, and catalog. Keep an independent backup before an upgrade. Do not run the server from an arbitrary directory containing private files.

## Development checks

Node.js is needed only for the isolated frontend function tests.

```sh
python3 -m unittest discover -s tests -p 'test_*.py'
cd assets/storyboard-studio
python3 -m unittest discover -s tests -p 'test_*.py'
node --check app.js
for test in tests/*.cjs; do node "$test" || exit; done
```

Tests use disposable projects and synthetic fixtures. They cover save recovery, identity, board isolation, migrations, chosen paths, reference handling, launch ownership, media imports, and renderer-free handoff admission. Frontend function tests mock the DOM; they do not prove physical trackpad behavior, native annotation support, or an actual renderer round trip. This public packaging pass did not perform those integration checks.

## License

Original code, icons, and synthetic examples are MIT licensed, copyright Exlumina contributors. System fonts remain on the user's device. FFmpeg is an optional separately installed executable governed by the license of your selected build; it is not distributed in this repository or release ZIP. See [LICENSE](LICENSE) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Report reproducible bugs through GitHub Issues using synthetic projects. Remove private source paths, actual media, project history, and credentials before sharing diagnostic files.
