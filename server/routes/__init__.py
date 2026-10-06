"""The site's routes, one module per part of the URL space.

Each module has a `..._router(templates)` function that builds an `APIRouter`, which
`create_app` in `server/app.py` includes. What more than one of them needs is in
`server/routes/common.py`. See docs/randomizer_devplan.md, "Routes".
"""
