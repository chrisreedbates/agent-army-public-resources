from atlas.storage.local import LocalStorage


def test_local_storage_writes_versions_and_lists_docs(tmp_path):
    storage = LocalStorage(tmp_path)

    assert storage.write_doc("company assessment", {"title": "Company"}) == 1
    assert storage.write_doc("company assessment", {"title": "Company v2"}) == 2

    doc = storage.read_doc("company assessment")
    docs = storage.list_docs()

    assert doc["key"] == "company assessment"
    assert doc["version"] == 2
    assert docs == [
        {
            "key": "company assessment",
            "title": "Company v2",
            "category": "",
            "summary": "",
            "confidence": "",
            "version": 2,
            "updated_at": doc["updated_at"],
        }
    ]
