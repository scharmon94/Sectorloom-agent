# Building the Windows installer

The installer is built by GitHub Actions on a real Windows machine. You
do not need Windows, Python, or NSIS on your own computer to get one.

## What comes out

| File | What it is |
|---|---|
| `SectorLoomSetup.exe` | What drivers download. Installs the agent, no Python needed. |
| `SectorLoomAgent.exe` | The bare program, for anyone who would rather not run an installer. |

## First-time setup

1. Create a repository on GitHub — **public**. The site's FAQ tells
   people the agent's source is open and that the installer is built
   from it in public, which is a fair thing to offer for an unsigned
   program they are about to trust. A private repository would make
   that sentence untrue, so make it public or tell me and I will
   reword the FAQ.

2. Push this folder to it:

   ```
   cd agent
   git init
   git add .
   git commit -m "SectorLoom telemetry agent"
   git branch -M main
   git remote add origin https://github.com/<you>/sectorloom-agent.git
   git push -u origin main
   ```

3. That push starts the first build. Watch it under the **Actions** tab.
   It takes about five minutes, most of it PyInstaller.

Nothing else to configure. No secrets, no tokens, no settings — the
workflow uses the token GitHub gives every run.

## Getting the installer

**For a test build:** Actions → the run → **Artifacts** at the bottom →
`SectorLoomSetup-0.0.<n>`. It downloads as a zip; the exe is inside.

**For a release people will use:**

```
git tag v1.0.0
git push origin v1.0.0
```

That build attaches both exes to a GitHub Release, with a permanent
download link:

```
https://github.com/<you>/sectorloom-agent/releases/latest/download/SectorLoomSetup.exe
```

You can either drop the exe into `upload-this-folder` next to
`index.html`, or point `AGENT_DOWNLOAD` in `config.js` at that link —
in which case shipping a new agent takes a tag and nothing else, with
no site re-upload at all.

## What the build checks before it hands you anything

- the agent still imports, including its GUI
- the 26 end-to-end checks in `tests/test_end_to_end.py`, which run the
  agent against a stand-in Supabase with real generated telemetry
- the installer installs **silently and for real on the runner**: the
  exe lands in place, the start-with-Windows entry is written, the
  Start Menu shortcut exists, the Add/Remove Programs entry exists —
  and then that uninstalling removes all of it again

A failure in any of those fails the build rather than shipping.

## Building it by hand

On Windows, with Python and [NSIS](https://nsis.sourceforge.io)
installed:

```
build-windows.bat
makensis /DVERSION=1.0.0 /DAGENT_EXE=..\dist\SectorLoomAgent.exe ^
         /DOUTFILE=..\dist\SectorLoomSetup.exe installer\sectorloom.nsi
```

On Linux or macOS you can compile and check the installer script
itself, though not the agent inside it — `makensis` is cross-platform
and PyInstaller is not:

```
makensis -DVERSION=1.0.0 -DAGENT_EXE=/path/to/any/file \
         -DOUTFILE=/tmp/SectorLoomSetup.exe installer/sectorloom.nsi
```

## About the SmartScreen warning

`SectorLoomSetup.exe` is not code-signed, so Windows shows "Windows
protected your PC" to everyone who runs it until the file builds
reputation. The site's FAQ explains this in plain words rather than
pretending it will not happen.

Signing is the only real fix. When it is worth paying for, it is one
step in the workflow (`signtool` between the PyInstaller step and the
NSIS step, and again on the installer) plus the certificate itself —
Azure Trusted Signing is around $10/month but wants a legal entity
with three years of history; a conventional certificate from Sectigo
or DigiCert runs $200–400 a year and will take an individual.
