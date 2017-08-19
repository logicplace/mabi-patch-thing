Script to grab updates.

# Usage #
Download the latest patch: `python3 download.py`

Download the full latest release version: `python3 download.py -f`

Download a specific version: `python3 download.py -d VERSION`

You may also download the full of a specific version with `-fd`

Show extra info: `-v`

Update Mabi installation `python3 download.py -u C:\path\to\Nexon\Mabinogi`

or just `python3 download.py -u` if you're in the mabi folder.

# Detailed usage #
    -u Indicates you wish to download the difference between two versions.
       By default this is the difference between the installed files and the latest version. 
    -d Specifies the target version to download. The base version is either
       the currently installed version, what's specified in -F, or the previous version.
    -F Specify the version you wish to patch from. Generally not needed.
    -f Download the full release instead of a patch.
       -fu is kind of redundant.
       -fd downloads the full release of the specified version. Ignores -F
           This will overwrite existing files.
       -fud continues a full download of the specified version. Ignores -F
    -m Downloads the manifest to manifest.json. It does not prevent updating.
    -v Shows more information, like what files are downloading.
    -vv Shoes debug information you likely won't need.
