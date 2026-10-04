import subprocess

from esbi_cli.gitops import commit_vault, push_vault


def log(vault):
    return subprocess.run(
        ["git", "log", "--format=%s"], cwd=vault.root, capture_output=True, text=True
    ).stdout.split("\n")[:-1]


def test_committing_works_when_a_managed_folder_exists_but_is_still_empty(vault):
    # a fresh vault: raw/ exists on disk, but git cannot track an empty folder
    assert list((vault.root / "raw").iterdir()) == []
    (vault.wiki / "sources" / "Nota.md").write_text(
        "---\ntitle: Nota\n---\ntexto", encoding="utf-8"
    )

    assert commit_vault(vault.root, "primera") is True

    assert log(vault) == ["primera"]
    assert commit_vault(vault.root, "otra vez") is False  # nothing new to commit


def test_the_vault_is_pushed_to_its_backup_remote_when_it_has_one(vault, tmp_path):
    (vault.wiki / "sources" / "Nota.md").write_text(
        "---\ntitle: Nota\n---\ntexto", encoding="utf-8"
    )
    commit_vault(vault.root, "primera")
    assert push_vault(vault.root) is None  # no remote: nothing to do, not an error

    bare = tmp_path / "backup.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(bare)], check=True)
    subprocess.run(["git", "remote", "add", "origin", str(bare)], cwd=vault.root, check=True)

    assert push_vault(vault.root) is None
    on_remote = subprocess.run(
        ["git", "log", "--format=%s", "main"], cwd=bare, capture_output=True, text=True
    ).stdout
    assert on_remote.split() == ["primera"]


def test_a_backup_that_cannot_be_reached_is_reported_and_never_raises(vault, tmp_path):
    subprocess.run(
        ["git", "remote", "add", "origin", str(tmp_path / "nowhere.git")],
        cwd=vault.root,
        check=True,
    )
    (vault.wiki / "sources" / "Nota.md").write_text(
        "---\ntitle: Nota\n---\ntexto", encoding="utf-8"
    )
    commit_vault(vault.root, "primera")

    problem = push_vault(vault.root)

    assert problem and "nowhere.git" in problem


def tracked(vault):
    return set(
        subprocess.run(
            ["git", "ls-files"], cwd=vault.root, capture_output=True, text=True
        ).stdout.split()
    )


def test_the_schema_and_the_golden_questions_are_versioned_but_the_rest_of_the_state_is_not(vault):
    (vault.root / ".gitignore").write_text(".esbi/*\n!.esbi/golden.jsonl\n", encoding="utf-8")
    (vault.root / ".esbi").mkdir()
    (vault.root / ".esbi" / "golden.jsonl").write_text('{"question": "q"}\n', encoding="utf-8")
    (vault.root / ".esbi" / "queue.sqlite3").write_text("x", encoding="utf-8")
    (vault.root / "inbox" / "mine.md").write_text("x", encoding="utf-8")
    (vault.root / ".obsidian").mkdir()
    (vault.root / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")
    (vault.wiki / "sources" / "Nota.md").write_text("---\ntitle: Nota\n---\nx", encoding="utf-8")

    assert commit_vault(vault.root, "primera") is True

    assert tracked(vault) == {
        "SCHEMA.md",
        ".esbi/golden.jsonl",
        "wiki/sources/Nota.md",
        "index.md",
        "log.md",
    }
    (vault.root / "SCHEMA.md").write_text("# mi esquema\n", encoding="utf-8")
    assert commit_vault(vault.root, "esquema") is True  # an edit of the schema is a change


def test_a_vault_that_ignores_the_whole_state_folder_is_upgraded_the_first_time_it_is_committed(
    vault,
):
    ignore = vault.root / ".gitignore"
    ignore.write_text(".DS_Store\n.esbi/\n.trash/\n", encoding="utf-8")
    (vault.root / ".esbi").mkdir()
    (vault.root / ".esbi" / "golden.jsonl").write_text('{"question": "q"}\n', encoding="utf-8")
    (vault.root / ".esbi" / "runs.jsonl").write_text("{}\n", encoding="utf-8")

    assert commit_vault(vault.root, "primera") is True
    assert commit_vault(vault.root, "otra") is False  # idempotent

    assert ".esbi/golden.jsonl" in tracked(vault) and ".esbi/runs.jsonl" not in tracked(vault)
    assert ignore.read_text().splitlines() == [
        ".DS_Store",
        ".esbi/*",
        "!.esbi/golden.jsonl",
        ".trash/",
    ]


def test_loading_the_config_does_not_undo_the_upgraded_ignore_rule(vault, tmp_path):
    from esbi_cli.config import load_config

    (vault.root / ".gitignore").write_text(".esbi/\n", encoding="utf-8")
    (vault.root / ".esbi").mkdir()
    config = tmp_path / "config.toml"
    config.write_text(f'[paths]\nvault = "{vault.root}"\n', encoding="utf-8")

    load_config(config)
    load_config(config)

    assert (vault.root / ".gitignore").read_text().splitlines() == [
        ".esbi/*",
        "!.esbi/golden.jsonl",
    ]


def test_a_managed_file_that_the_users_own_ignore_rules_hide_never_breaks_the_commit(vault):
    (vault.root / ".gitignore").write_text("SCHEMA.md\n", encoding="utf-8")
    (vault.wiki / "sources" / "Nota.md").write_text("---\ntitle: Nota\n---\nx", encoding="utf-8")

    assert commit_vault(vault.root, "primera") is True
    assert "SCHEMA.md" not in tracked(vault)
