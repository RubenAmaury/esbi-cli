# Homebrew formula for esbi-cli. It lives in a tap (a repo named homebrew-esbi-cli, folder
# Formula/); this copy is the source of truth. `scripts/release.sh` prints the two lines that change
# for each release (tag and revision).
class EsbiCli < Formula
  desc "Worker that keeps a Markdown wiki (Obsidian-compatible) up to date from your saved sources"
  homepage "https://github.com/RubenAmaury/esbi-cli"
  # A git url, not a tarball: it also works while the repository is private (git uses your credentials)
  url "https://github.com/RubenAmaury/esbi-cli.git",
      tag:      "v0.1.0",
      revision: "REPLACE_WITH_THE_COMMIT_OF_THE_TAG"
  license "MIT"
  head "https://github.com/RubenAmaury/esbi-cli.git", branch: "main"

  include Language::Python::Virtualenv

  depends_on "python@3.13"

  def install
    venv = virtualenv_create(libexec, "python3.13")
    # Dependencies come from PyPI as wheels (pymupdf and lxml are not built from source here)
    system libexec/"bin/python", "-m", "pip", "install", "--no-cache-dir", buildpath
    bin.install_symlink libexec/"bin/sb"
  end

  def caveats
    <<~EOS
      First time:   sb init --model local        (or --model subscription)
      Then:         sb doctor
      The nightly job (macOS):  sb schedule install
      Local models need Ollama: brew install ollama && ollama pull llama3.2
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/sb version")
    system bin/"sb", "init", "--vault", testpath/"Brain", "--config-file", testpath/"config.toml"
    assert_predicate testpath/"Brain/SCHEMA.md", :exist?
  end
end
