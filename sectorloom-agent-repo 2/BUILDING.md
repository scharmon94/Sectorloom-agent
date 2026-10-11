# Building the Windows installer

The installer is built by GitHub Actions on a real Windows machine. You
do not need Windows, Python, or NSIS on your own computer to get one.

## What comes out

| File | What it is |
|---|---|
| `SectorLoomSetup.exe` | What drivers download. Installs the agent, no Python needed. |
| `SectorLoomAgent.exe` | The bare program, for anyone who would rather not run an installer. |

## First-time setup

1. Create a repository on GitHub — **private**. Nothing here needs to
   be public, and the site's FAQ makes no claim that it is.

   A private repository on the GitHub Free plan gets 2,000 Actions
   minutes a month, and a Windows build takes about five minutes and
   draws those minutes down faster than a Linux one would. That is
   still well over a hundred builds a month, which is far more than
   this will ever need. Public repositories get standard runners free,
   so if you ever run out, making it public is the escape hatch.

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

That build attaches both exes to a GitHub Release, which keeps a tidy
history of what shipped when.

**It does NOT give you a link drivers can use.** Release assets on a
*private* repository need a signed-in GitHub account with access to
that repo; an anonymous visitor gets a 404. The release is for your
records. The file drivers download comes from R2 — next section.


## Where the installer is hosted

Not on Cloudflare Pages. Pages caps a single file at 25 MiB and the
installer is around 50 MB, which is ordinary for a bundled Python app
carrying numpy and duckdb. duckdb alone is a single 38 MB native
extension, so there is no trimming that gets under the cap without
dropping Le Mans Ultimate support.

It lives in a **Cloudflare R2 bucket** instead, on the same account as
the site:

1. Cloudflare dashboard -> **R2** -> *Create bucket*, e.g.
   `sectorloom-downloads`.
2. Upload `SectorLoomSetup.exe` into it.
3. Bucket -> **Settings** -> *Public access* -> **Custom Domains** ->
   *Connect Domain* -> `downloads.sectorloom.com`. Because the zone is
   on the same account, Cloudflare writes the DNS record itself.

   Use a custom domain rather than turning on the `r2.dev` address:
   Cloudflare rate-limits `r2.dev` and says plainly it is for
   development, not production traffic.
4. In `config.js`:

   ```js
   AGENT_DOWNLOAD: "https://downloads.sectorloom.com/SectorLoomSetup.exe",
   ```

5. Re-deploy the site once. After that, shipping a new agent is just
   replacing the object in the bucket — no site deploy at all.

If a browser ever opens the file instead of downloading it, set the
object's **Content-Disposition** to `attachment` in R2's object
settings. (The `download` attribute on the site's link is ignored for
cross-origin URLs, which is why the header is what decides it.)

R2 charges nothing for bandwidth, which is its whole reason for
existing, and a 50 MB file is nothing against the free storage
allowance. Check the current free-tier figures on Cloudflare's R2
pricing page if you want the exact numbers.

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

Publishing the SHA-256 of each release on the download page is worth
doing at some point. It lets a careful person check that the file they
downloaded is the one you built, which is the one thing a signature
would otherwise give them. `certutil -hashfile SectorLoomSetup.exe
SHA256` prints it on any Windows machine.

Signing is the only real fix. When it is worth paying for, it is one
step in the workflow (`signtool` between the PyInstaller step and the
NSIS step, and again on the installer) plus the certificate itself —
Azure Trusted Signing is around $10/month but wants a legal entity
with three years of history; a conventional certificate from Sectigo
or DigiCert runs $200–400 a year and will take an individual.
