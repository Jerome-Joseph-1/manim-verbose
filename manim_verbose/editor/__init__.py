"""
The browser editor for scene files, and the local server behind it.

    server.py     create_app: the HTTP API (docs/editor/server-api.md) and the built editor UI
    documents.py  the scene file being edited: revisions, conflicts, atomic saves
    workers.py    render worker processes: kept warm, killed and restarted when stuck
    jobs.py       what renders when: stills (newest wins), clips and exports
    outputs.py    the output folder, which is also the render cache
    backend.py    what the server needs from scenefile's renderer, behind one object
    catalog.py    the objects and steps the editor offers, with templates
    starter.py    the document a new scene file starts as
    cli.py        manimgl-editor

The UI itself is built from editor-ui/ into static/ here.
"""
