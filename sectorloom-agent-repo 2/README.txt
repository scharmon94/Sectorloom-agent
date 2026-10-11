SECTORLOOM TELEMETRY AGENT
==========================

A small Windows program that watches your sim's telemetry folder and
uploads each session to your SectorLoom account as you finish it. You
never have to drag a file into the website again.

It works with iRacing (.ibt) and Le Mans Ultimate. Assetto Corsa
Competizione and the original Assetto Corsa are not supported yet.


WHAT YOU NEED FIRST
-------------------

1. A SectorLoom account. Sign up on the website.

2. iRacing telemetry switched on. In a session press Alt+L, or set
   irsdkLog=1 in Documents\iRacing\app.ini. Files land in
   Documents\iRacing\telemetry.

   Le Mans Ultimate: turn telemetry on under Gameplay settings, or bind
   a button to it. Files land in ...\Le Mans Ultimate\UserData\Telemetry.


INSTALLING IT
-------------

Click "Download agent" in the SectorLoom header, then run the file you
get (SectorLoomSetup.exe). That is the whole thing. No Python, no
unzipping, no administrator password.

Windows will show a blue "Windows protected your PC" box the first
time. Click "More info", then "Run anyway". That box appears because
the program is not code-signed, not because Windows found anything
wrong with it — a signing certificate costs a few hundred dollars a
year and has not been bought. Every new program from a small publisher
gets the same box.

The installer puts the agent in your own user folder
(%LOCALAPPDATA%\Programs\SectorLoom), adds a Start Menu shortcut,
sets it to start with Windows, and opens it when it finishes. You can
turn off starting with Windows in the agent's own settings window.

To remove it: Settings -> Apps -> Installed apps -> SectorLoom
Telemetry Agent -> Uninstall. Your sign-in and folder settings in
%APPDATA%\SectorLoom are left alone so a reinstall is not a fresh
start; delete that folder as well if you want nothing left.


RUNNING IT FROM THE SOURCE INSTEAD
----------------------------------

If you would rather not run a program you cannot read, everything here
is plain Python. Install Python 3.10 or newer from python.org, ticking
"Add python.exe to PATH", then double-click run.bat. It does exactly
what the installed version does.


SETTING IT UP
-------------

The window asks for three things:

  Site address   already filled in as sectorloom.com. Leave it alone
                 unless you were given a different address.
  Email          the one you sign in to SectorLoom with
  Password       used once, to sign in. It is not stored: the agent
                 keeps a session token instead, like a browser does.

That is everything. The agent reads the rest of what it needs from the
site itself, so there is nothing to look up and no keys to copy.

Then tick the sims you want watched. The folders are filled in for you
if they are where the sims normally put them; point them somewhere else
if yours are not.

"Start with Windows" puts the agent in your own startup list. It needs
no administrator rights and you can turn it off in the same place.


WHAT IT ACTUALLY SENDS
----------------------

The agent reads and understands the telemetry on your own machine and
uploads only the finished session — roughly 400 KB for nine laps, where
the raw file is about 30 MB. Your raw telemetry files never leave your
computer.


IF SOMETHING LOOKS WRONG
------------------------

The window keeps a log of everything it has done. Most problems show up
there in plain words.

A file it could not read is remembered rather than retried forever;
"Retry failed files" has another go at all of them.

For a Le Mans Ultimate file it cannot make sense of, run this from the
folder and send the output on — it prints every table and column it
found, which is what is needed to teach it that layout:

    py -3 run_agent.py --probe "path\to\the\file"

(If you installed rather than running from source, the same thing is
    "%LOCALAPPDATA%\Programs\SectorLoom\SectorLoomAgent.exe" --probe "path\to\the\file"
)

Your settings live in  %APPDATA%\SectorLoom\agent.json
(If you used this when it was called Lapwise, your settings are carried
over from the old folder the first time you run it. You will not have to
sign in again.)
