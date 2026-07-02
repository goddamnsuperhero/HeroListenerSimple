# Overrides the pyinstaller-hooks-contrib webrtcvad hook, which calls
# copy_metadata('webrtcvad') and crashes here because the installed distribution is
# 'webrtcvad-wheels' (prebuilt wheels), not 'webrtcvad'. The C extension itself is
# collected via collect_all('webrtcvad') in the .spec; the metadata isn't needed at
# runtime, so fall back to empty if the dist name can't be found.
from PyInstaller.utils.hooks import copy_metadata

datas = []
for _dist in ("webrtcvad-wheels", "webrtcvad"):
    try:
        datas = copy_metadata(_dist)
        break
    except Exception:
        continue
