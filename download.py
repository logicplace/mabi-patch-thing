#!/usr/bin/env python
#-*- coding:utf-8 -*-

import urllib2, re, sys, ftplib, os, hashlib, struct
from zipfile import ZipFile

FILEBASE = ""
WARNING = "If the game is currently in maintenance, the patch may be updated again later. Are you sure you want to continue?"

class CleanExit(Exception): pass

def yn(msg):
	x = "."
	while x not in "yYnN": x = raw_input(msg + " (y/n)? ")
	if x in "nN": raise CleanExit
#enddef

def main():
	# Check if the game is down
	ca = False
	patchinfo = {
		"main_ftp": "mabipatch.nexon.net",
		"lang": "patch_langpack.txt"
	}
	try: h = urllib2.urlopen("http://www.nexon.net/json/game_status.js")
	except urllib2.HTTPError as err:
		print "Failed to retrieve Game Status."
		print err
		print WARNING
		ca = True
	else:
		raw = h.read()
		h.close()
		mo = re.search(r'"SVG012" *: *([^,]+) *,', raw)
		if not mo:
			print "Couldn't check game status. " + WARNING
			ca = True
		else:
			mo = mo.group(1).lower()
			# Mild future-proofing
			if mo in ["true", "1"]: print "Game is currently ONLINE."
			elif mo in ["false", "0"]:
				print "Game is currently OFFLINE. " + WARNING
				ca = True
			#endif
		#endif
	#endtry

	# Check for the current version
	try: h = urllib2.urlopen("http://mabipatchinfo.nexon.net/patch/patch.txt")
	except urllib2.HTTPError as err:
		print "Failed to retrieve Patch Information."
		print err
		print "Using default FTP and langpack addresses"
		ddef = None
	else:
		ln = h.readline()
		while ln:
			try: k, v = tuple(ln.rstrip().split("="))
			except ValueError: patchinfo[ln] = True
			else: patchinfo[k] = v
			ln = h.readline()
		#endwhile
		h.close()

		if patchinfo["patch_accept"] != "1":
			print "Server is indicating that the latest patch should not be downloaded at this time."
			ca = True
		#endif

		patchinfo["main_ftp"] = patchinfo["main_ftp"].split("/", 1)[0]
		ddef = patchinfo["main_version"]
	#endtry

	ftp = ftplib.FTP("mabipatch.nexon.net")
	ftp.login("anonymous", "")

	while True:
		if ddef:
			download = raw_input("Enter the version to download (%s): " % patchinfo["main_version"])
			if not download: download = patchinfo["main_version"]
		else:
			download = ""
			while not download: download = raw_input("Enter the version to download: ")
		#endif

		# Check if it exists
		try: ftp.cwd("/" + download)
		except ftplib.error_perm as err:
			if err.args[0][0:4] != "550 ": print "Unhandled FTP error: " + err.args[0]
		else: break
	#endwhile

	# From?
	while True:
		pfrom = raw_input("From which version (all)? ").lower()
		if not pfrom:
			pfrom = "all"
			break
		elif pfrom == "full": pfrom = download + "_full.txt"
		else: pfrom = "%s_to_%s.txt" % (pfrom, download)
		try: ftp.size(pfrom)
		except ftplib.error_perm as err:
			if err.args[0][0:4] != "550 ": print "Unhandled FTP error: " + err.args[0]
		else: break
	#endwhile

	if ca: yn("Continue anyway")

	# Downloads!
	path = os.path.join(FILEBASE, download)
	try: os.makedirs(path)
	except OSError as err:
		if err.errno != 17: raise
	#endtry

	download_lang(ftp, path, patchinfo["lang"])
	if pfrom == "all":
		download_txt(ftp, path, download + "_full.txt")
		v = int(download) - 1
		make_patch(path, download + "_full.txt", download)
		while download_txt(ftp, path, "%i_to_%s.txt" % (v, download)):
			make_patch(path, "%i_to_%s.txt" % (v, download), download)
			v -= 1
		#endwhile
	else:
		download_txt(ftp, path, pfrom)
		make_patch(path, pfrom, download)
	#endif
#enddef

def read_verify(fn, cb):
	ret = True
	f = open(fn, "r")
	try: numlines = int(f.readline())
	except ValueError:
		print "Unknown verification file format. (NF)" # Number First
		return False
	#entry

	for i in range(numlines):
		ln = f.readline().rstrip()
		try:
			fn, size, md5 = tuple(ln.split(", "))
			size = int(size)
		except ValueError:
			print "Unknown verification file format. (BL)" # Bad Line
			print ln
			return False
		#endtry
		cb(fn, size, md5)
	#endfor

	f.close()
#enddef

def download_txt(ftp, path, txt):
	print "Downloading verification file: " + txt
	fn = os.path.join(path, txt)
	f = open(fn, "w")
	try: ftp.retrbinary("RETR " + txt, f.write)
	except ftplib.error_perm as err:
		if err.args[0][0:4] != "550 ": print "Unhandled FTP error: " + err.args[0]
		f.close()
		return False
	#endtry
	f.close()

	ret = [True]
	def tmp(fn, size, md5):
		sfn = os.path.join(path, fn)
		try: f2 = open(sfn, "r")
		except IOError as err:
			if err.errno != 2: raise
			test = download_file(ftp, path, fn)
		else:
			# Already exists
			f2.seek(0, 2)
			csize = f2.tell()
			f2.close()
			print "File %s already exists." % fn,
			if csize < size:
				print "Continuing download..."
				test = download_file(ftp, path, fn, csize)
			elif verify_file(sfn, size, md5): return
			else:
				"Attempting redownload..."
				test = download_file(ftp, path, fn)
			#endif
		#entry
		if not test or not verify_file(sfn, size, md5): ret = False
	#endfor
	read_verify(fn, tmp)

	return ret
#enddef

def download_lang(ftp, path, lang):
	print "Downloading lang file: " + lang
	fn = os.path.join(path, lang)
	f = open(fn, "wb")
	try: ftp.retrbinary("RETR " + lang, f.write)
	except ftplib.error_perm as err:
		if err.args[0][0:4] != "550 ": print "Unhandled FTP error: " + err.args[0]
		f.close()
		return False
	#endtry
	f.close()
	f = open(fn, "rb")
	f.seek(0x28)
	langfn = f.read()
	f.close()
	return download_file(ftp, path, langfn)
#enddef

def download_file(ftp, path, fn, rest=None):
	print "Downloading file: " + fn
	sfn = os.path.join(path, fn)
	if rest: f = open(sfn, "ab")
	else: f = open(sfn, "wb")
	try: ftp.retrbinary("RETR " + fn, f.write, rest=rest)
	except ftplib.error_perm as err:
		if err.args[0][0:4] != "550 ": print "Unhandled FTP error: " + err.args[0]
		f.close()
		return False
	#endtry
	f.close()
	return True
#enddef

def verify_file(fn, size, md5):
	print "Verifying file: " + fn,
	f = open(fn, "rb")
	f.seek(0, 2)
	if size != f.tell():
		print "Size check failed. Expected: %i, Actual: %i" % (size, f.tell())
		f.close()
		return False
	else:
		f.seek(0, 0)
		m = hashlib.md5()
		while True:
			data = f.read(1048576)
			if not data: break
			m.update(data)
		#endwhile
		if md5 != m.hexdigest():
			print "MD5 checksum failed. Expected: %s, Actual: %s" % (md5, m.hexdigest())
			f.close()
			return False
		#endif
	#endif
	f.close()
	print "OK"
	return True
#enddef

def make_patch(path, fn, ver):
	basename = fn.split(".", 1)[0]
	print "Making patch for " + basename
	# Concat
	path2 = os.path.join(path, "patch")
	unpackdir = os.path.join(path2, basename)
	zipfn = os.path.join(path2, basename + ".zip")
	try: os.makedirs(unpackdir)
	except OSError as err:
		if err.errno != 17: raise
	#endtry

	f2 = open(zipfn, "wb")
	def tmp(fn, size, md5):
		f1 = open(os.path.join(path, fn), "rb")
		while True:
			data = f1.read(1048576)
			if not data: break
			f2.write(data)
		#endwhile
		f1.close()
	#enddef
	print "Merging..."
	read_verify(os.path.join(path, fn), tmp)
	f2.close()

	# Unpack
	print "Unpacking..."
	zf = ZipFile(zipfn, allowZip64=True)
	try: os.makedirs(unpackdir)
	except OSError as err:
		if err.errno != 17: raise
	#endtry
	for zfn in zf.namelist():
		to = os.path.join(*([unpackdir] + zfn.split("\\")[0:-1]))
		zf.extract(zfn, to)
		os.rename(os.path.join(to, zfn), os.path.join(to, zfn.split("\\")[-1]))
	#endfor
	zf.close()

	# If there isn't a language pack, add one.
	print "Extracting language pack..."
	packdir = os.path.join(unpackdir, "package")
	if not os.path.isfile(os.path.join(packdir, "language.pack")):
		langzip = os.path.join(path2, ver + "_language.zip")
		langp_ = os.path.join(path, ver + "_language.p_")
		if os.path.isfile(langzip):
			lz = ZipFile(langzip)
			lz.extractall(packdir)
		elif os.path.isfile(langp_):
			ff = open(langp_, "rb")
			ft = open(langzip, "wb")
			ft.write(ff.read())
			ff.close()
			ft.close()
			lz = ZipFile(langzip)
			lz.extractall(packdir)
		else:
			print "No language pack found."
		#endif
	#endif

	# Makever
	print "Creating version.dat..."
	f = open(os.path.join(unpackdir, "version.dat"), "wb")
	f.write(struct.pack("<I", int(ver)))
	f.close()

	# Repack
	print "Repacking..."
	os.unlink(zipfn)
	zf = ZipFile(zipfn, "w", allowZip64=True)
	for root, dirs, files in os.walk(unpackdir, False):
		for fn in files:
			p = os.path.join(root, fn)
			zf.write(p, p[len(unpackdir):])
			os.unlink(p)
		#endfor
		for d in dirs: os.rmdir(os.path.join(root, d))
	#endfor
	zf.close()
	os.rmdir(unpackdir)

	print "Patch complete."
#enddef

if __name__ == "__main__":
	try: sys.exit(main())
	except (EOFError, KeyboardInterrupt):
		print "\nOperations terminated by user."
		sys.exit(0)
	except CleanExit: sys.exit(0)
#endif
