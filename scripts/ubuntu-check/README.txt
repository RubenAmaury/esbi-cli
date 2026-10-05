Ubuntu checks for esbi-cli (WSL's default distro is Ubuntu). For the `testing` branch only; never a PR to main.

Each sN_*.sh runs in a FRESH ubuntu container (1 GB memory limit, fresh non-root user "tester", empty HOME,
no repo checkout) through ub.sh:

  APT="git" ./ub.sh 24.04 s3_ingest.sh          # APT = extra packages; ROOT=1 runs the script as root;
  EXTRA="--privileged" ROOT=1 ./ub.sh 24.04 s6_vfat.sh   # EXTRA = more `docker run` flags

- By default esbi-cli comes from PyPI (uv tool install esbi-cli). WHEEL=1 installs /dist/esbi_cli-*.whl
  instead: `uv build -o /tmp/dist-linux` first (ub.sh mounts /tmp/dist-linux at /dist).
- fake_ollama.py is a stdlib fake Ollama (valid JSON for every schema); no model, no GPU. DELAY=4 slows each call.
- s3 and s4a expect a pdfs/ folder next to the scripts (copy tests/fixtures/pdf/{plain-text,twelve-pages,scan-1page}.pdf
  and any multi-page paper as attention.pdf).
- s6_vfat.sh mounts a vfat image at "/mnt/c/Users/Ruben Melo/Documents": the nearest container stand-in for WSL's
  /mnt/c (case-insensitive, no permissions). Indicative only: vfat is not NTFS.
- Needs Docker; only the ubuntu:22.04 and ubuntu:24.04 images are used.
