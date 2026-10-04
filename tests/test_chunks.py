from esbi_cli.ingest.chunks import split_chunks


def paragraphs(n, size=1000):
    return [f"P{i:02d} " + "x" * (size - 4) for i in range(n)]


def test_text_is_split_at_paragraph_boundaries_into_chunks_no_bigger_than_the_size():
    text = "\n\n".join(f"Párrafo {i}. " + "palabra " * 100 for i in range(20))

    chunks = split_chunks(text, size=2500)

    assert len(chunks) >= 6 and all(len(c) <= 2500 for c in chunks)
    joined = "\n\n".join(chunks)
    assert all(f"Párrafo {i}." in joined for i in range(20))  # nothing lost
    assert all(c.startswith("Párrafo") for c in chunks)  # cut between paragraphs, not inside


def test_a_paragraph_bigger_than_a_chunk_is_cut_hard():
    chunks = split_chunks("x" * 5000, size=2000)
    assert [len(c) for c in chunks] == [2000, 2000, 1000]


def test_the_reference_list_is_dropped_but_only_when_it_is_near_the_end():
    body = "\n\n".join(paragraphs(10))
    late = split_chunks(body + "\n\nReferences\n\n[1] A. Author. Some paper. 2020.", size=20000)
    assert "Some paper" not in " ".join(late) and "P09" in " ".join(late)

    early = split_chunks(
        "Intro\n\nReferences\n\nnot a bibliography, just a heading\n\n" + body, size=20000
    )
    assert "just a heading" in " ".join(early)  # a heading early on is content


def test_huge_sources_are_sampled_from_the_start_the_end_and_evenly_between():
    chunks = split_chunks("\n\n".join(paragraphs(40)), size=1000, max_chunks=10)

    names = [c[:3] for c in chunks]
    assert len(chunks) == 10 and names == sorted(set(names))  # in order, no repeats
    assert names[:3] == ["P00", "P01", "P02"] and names[-2:] == ["P38", "P39"]
