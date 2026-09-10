import sys
from pathlib import Path
import pycdlib

directory = Path(sys.argv[1])
iso = pycdlib.PyCdlib()
iso.new(interchange_level=3, joliet=3, rock_ridge="1.09", vol_ident="cidata")
iso.add_file(str(directory / "user-data"), iso_path="/USER.;1", rr_name="user-data", joliet_path="/user-data")
iso.add_file(str(directory / "meta-data"), iso_path="/META.;1", rr_name="meta-data", joliet_path="/meta-data")
iso.write(str(directory / "seed.iso"))
iso.close()
