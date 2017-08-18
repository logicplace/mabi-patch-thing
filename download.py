#!/usr/bin/env python3
#-*- coding:utf-8 -*-

# Copyright 2017 Sapphire Becker (logicplace.com)
# MIT Licensed

import os, sys, argparse, logging
import json
import zlib
import base64
import struct
import urllib.request
import urllib.error


try: import NexonAPI
except ImportError:
	NexonAPI = None
else:
	import getpass
#endtry


class PatchServerError(Exception): pass

class PatchServer:
	# Ideally one would log in and retrieve this from the Nexon API, but I'm not going to publish that!
	GAME_ID = "10200"
	BASE_URL = "https://download2.nexon.net/Game/nxl/games/" + GAME_ID + "/"

	HASH_URL = "{gameID}.{version}R.manifest.hash"
	MANIFEST_URL = "{hash}"
	PART_URL = "{gameID}/{part:.2}/{part}"

	def __init__(self):
		# But if you have a library for it already...
		if NexonAPI:
			self.BASE_URL = NexonAPI.getBaseURL()
		#endif

		self.local_version = None
		self.target_version = None
	#enddef

	def _getURL(self, url, fileName=None, serverName=None):
		try:
			return urllib.request.urlopen(url)
		except urllib.error.HTTPError as err:
			if fileName is None: fileName = url.split("/")[-1]
			raise PatchServerError("Error retrieving {}: {}".format(fileName, str(err)))
		except urllib.error.URLError as err:
			if serverName is None: serverName = url.split("/", maxsplit=3)[2]
			raise PatchServerError("Could not connect {}: {}".format(serverName, str(err)))
		#endtry
	#enddfe

	def getWebLaunchStatus(self):
		""" Returns true if the web launcher thinks the game is up. """
		conn = self._getURL("http://www.nexon.net/json/game_status.js", "status file")

		# Have to de-JSONp this.
		response = JSON.loads(conn.read()[len("nexon.games.playGame(") : -2])

		# This is Mabi's ID here
		status = response["SVG012"]
		logging.info("Web launch status is: {}.".format("UP" if status else "DOWN"))
		return status
	#enddef

	def legacyGetLatestVersion(self):
		""" Get the latest version as reported by the legacy launcher info. """
		conn = self._getURL("http://mabipatchinfo.nexon.net/patch/patch.txt", "patch info file")

		# Format is a list of var=val, one per line.
		txt = conn.read().split("\n")
		for line in txt:
			var, val = line.split("=", maxsplit=1)
			if var.strip() == "main_version": return int(val.strip())
		#endfor

		raise PatchServerError("Version not found in patch info.")
	#enddef

	def getLatestVersion(self):
		""" Get the latest version as reported by some server. """
		if NexonAPI is None:
			ver = legacyGetLatestVersion()
		else:
			ver = NexonAPI.getLatestVersion()
		#endif

		logging.info("Read latest version as {}.".format(ver))
		self.target_version = ver
		return ver
	#enddef

	def getLocalVersion(self, path):
		""" Get the verion of the Mabinogi installed at the given path. """
		try:
			with open(os.path.join(path, "version.dat"), "rb") as f:
				ver = struct.unpack("<I", f.read())[0]

				self.local_version = ver
				logging.info("Read local version as {}.".format(ver))
				return ver
			#endwith
		except FileNotFoundError:
			raise PatchServerError("Unable to find version.dat at " + path)
		#endif
	#enddef

	def getManifest(self, version=None):
		""" Get the manifest file from the server and decode it. """
		properties = {
			"gameID": self.GAME_ID,
			"version": version or self.target_version
		}

		# First download the hash
		hashURL = self.BASE_URL + self.HASH_URL.format(**properties)

		conn = self._getURL(hashURL, "hash file (" + hashURL + ")", "patch server")

		properties["hash"] = conn.read().strip().decode("utf8")

		logging.info("Hash downloaded.")

		# Now download the manifest
		manifestURL = self.BASE_URL + self.MANIFEST_URL.format(**properties)

		conn = self._getURL(manifestURL, "manifest file (" + manifestURL + ")", "patch server")
		
		manifest = conn.read()
		manifest = zlib.decompress(manifest)
		# TODO: handle zlib errors

		logging.info("Manifest decompressed.")

		manifest = json.loads(manifest.decode("utf8"))

		# Decode filenames.
		files = manifest["files"]
		keys = list(files.keys())
		encoding = manifest["filepath_encoding"]
		for key in keys:
			# Decode the filename.
			filename = os.path.join(*base64.b64decode(key).decode(encoding).split("\\"))
			files[filename] = files[key]
			del files[key]
		#endfor

		return manifest
	#enddef

	def diffManifests(self, m1, m2):
		""" Diff two manifests' files and return whether to create, update, or delete each changed file. """
		f1, f2 = m1["files"], m2["files"]
		changes, statuses = {}, {}
		updated, created, deleted = 0, 0, 0

		for fn, d2 in f2.items():
			if fn in f1:
				# Both versions have this file, compare mtime.
				d1 = f1[fn]
				if d1["mtime"] != d2["mtime"]:
					changes[fn] = d2
					statuses[fn] = "update"
					updated += 1
				#endif
			else:
				# This is a new file.
				changes[fn] = d2
				statuses[fn] = "create"
				created += 1
			#endif
		#endfor

		for fn in f1.keys():
			if fn not in f2:
				# This file was deleted.
				statuses[fn] = "delete"
				deleted += 1
			#endif
		#endfor

		logging.info("Files affected between the specified manifests: {} updated, {} created, {} deleted".format(updated, created, deleted))

		return changes, statuses
	#enddef

	def diffManifestWithFileSystem(self, manifest, path):
		""" Check the manifest against the path for updating. """
		# TODO
		pass
	#enddef

	def downloadFiles(self, path, files):
		""" The file list to download to path. """
		for fn, data in files.items():
			# Download parts.
			fsize = data["objects_fsize"]

			fpath = os.path.join(path, fn)

			# Don't worry about creating new folders, whatever checks the statuses should do that.
			try:
				with open(fpath, "wb") as f:
					logging.info("Downloading file " + fn)
					for i, obj in enumerate(data["objects"]):
						url = self.BASE_URL + self.PART_URL.format(gameID = self.GAME_ID, part = obj)
						conn = self._getURL(url, obj, "patch server")

						compressed = conn.read()
						clen = len(compressed)

						logging.info("  Downloaded part " + obj)

						decompressed = zlib.decompress(compressed)
						logging.debug("  Decompressed part " + obj)

						dlen = len(decompressed)
						
						# I dunno man
						if clen != fsize[i] and dlen != fsize[i]:
							logging.warn("  Unexpected filesize {} for part {}, expecting {}.".format(dlen, obj, fsize[i]))
						#endif

						f.write(decompressed)
						del decompressed
					#endfor
				#endwith

				# TODO: Check fsize

				# TODO: Don't change access time
				os.utime(fpath, times=(data["mtime"], data["mtime"]))

			except PatchServerError as err:
				logging.error("Failed to download file {}: {}".format(fn, str(err)))
				try: os.remove(path)
				except OSError: pass
			except IsADirectoryError:
				logging.error("Tried to overwrite a folder with the file " + fn)
			#endtry
		#endfor
	#enddef

	def updateFileSystem(self, base, statuses):
		""" Create new directories and delete files. """
		for fn, action in statuses.items():
			if action in ["create", "update"]:
				path = os.path.join(base, os.path.dirname(fn))
				os.makedirs(path, exist_ok=True)
			elif action == "delete":
				path = os.path.join(base, fn)
				try: os.remove(path)
				except OSError: pass
			#endif
		#endfor
	#enddef

	# Right now the dumb patcher system downloads from 183_full.pack and all the x_to_y.pack files after that
	# this is slow and gross so I hope they change it eventually. If they do, the code to handle it would
	# probably go in these functions, depending on how it's done.

	def update(self, path):
		""" Update the installation. """
		ver = self.getLatestVersion()

		manifest = self.getManifest(ver)

		changes, statuses = self.diffManifestWithFileSystem(manifest)
		self.updateFileSystem(path, statuses)

		# FUTURE?: Select only local_to_latest.pack if available.

		self.downloadFiles(path, changes)
	#enddef

	def download(self, path, f=None, t=None):
		""" Download patch f_to_t. """
		if f and not t:
			f, t = f - 1, f
		else:
			f = f or self.local_version or self.getLocalVersion(path)
			t = t or self.target_version or self.getLatestVersion()
		#endif

		m1 = self.getManifest(f)
		m2 = self.getManifest(t)

		changes, statuses = self.diffManifests(m1, m2)
		self.updateFileSystem(path, statuses)

		# FUTURE?: Select only f_to_t.pack if available.

		self.downloadFiles(path, changes)
	#enddef

	def downloadFull(self, path, version=None):
		""" Download all the files for this version. """
		version = version or self.target_version or self.getLatestVersion()

		manifest = self.getManifest(version)

		files = manifest["files"]

		statuses = {name: "create" for name in files.keys()}
		self.updateFileSystem(path, statuses)

		# FUTURE?: Select only version_full.pack if available.

		self.downloadFiles(path, files)
	#enddef
#endclass


def main(args):
	parser = argparse.ArgumentParser(description="Download Mabinogi NA patches.")
	g1 = parser.add_mutually_exclusive_group()
	g1.add_argument("-u", "--update", action="store_true",
		help="Update the mabi installation at the given location.")
	g2 = g1.add_argument_group()
	g2.add_argument("-d", "--download", default=None,
		help="Download a specific version.")
	g2.add_argument("-f", "--full", action="store_true",
		help="Download all the files instead of just updating.")
	parser.add_argument("-v", "--verbose", action="store_true",
		help="Print extra information.")
	parser.add_argument("path", nargs="?", default="",
		help="Base Mabinogi installation directory.")
	if NexonAPI:
		parser.add_argument("-u", "--username", default=None,
			help="Username to log in with.")
	#endif
	
	args = parser.parse_args(args)

	logging.basicConfig(
		level=logging.INFO if args.verbose else logging.WARNING,
		style="{", format="{levelname}: {message}",
	)

	if NexonAPI:
		username = args.username
		while not username: username = input("Enter username: ").strip()

		password = None
		while not password: password = getpass.getpass("Enter password: ")

		NexonAPI.login(username, password)
	#endif

	patcher = PatchServer()

	if not args.download and not patcher.getWebLaunchStatus():
		answer = input(
			"The web launcher indicates the game is down.\n"
			"If the game is down for maintainence for the current patch,\n"
			"there is a chance the patch could be changed before the game is back up.\n"
			"Do you want to continue (Y/N)? ")
		if answer.upper()[:1] != "Y": return 0
	#endif

	path = args.path or os.getcwd()

	if args.update:
		patcher.update(path)
		print("Update complete.")
	else:
		try:
			version = int(args.download)
		except ValueError:
			logging.error("Please enter a number for the version.")
			return 1
		#endtry

		if args.full:
			patcher.downloadFull(path, version)
		else:
			patcher.download(path, version)
		#endif
		print("Download complete.")
	#endif

	return 0
#enddef

if __name__ == "__main__":
	try: sys.exit(main(sys.argv[1:]))
	except (KeyboardInterrupt, EOFError):
		print("\nProgram terminated by user.")
	except PatchServerError as err:
		logging.error(str(err))
	#endtry
#endif
