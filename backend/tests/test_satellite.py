import unittest
import tempfile
import io
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from app import satellite_service as sat

class SatelliteTests(unittest.TestCase):
    def test_mosaic_location_transparency_and_catalog(self):
        image=Image.new('RGB',(256,256),(70,80,90));body=io.BytesIO();image.save(body,format='PNG')
        with tempfile.TemporaryDirectory() as root,patch.object(sat,'ROOT',Path(root)):
            sat.save_mosaic('20261013150000',[(7,3,body.getvalue()),(0,0,None)])
            with Image.open(sat.image_path('20261013150000')) as result:
                self.assertEqual(result.size,(2048,2048))
                self.assertEqual(result.getpixel((1792,768)),(70,80,90,255))
                self.assertEqual(result.getpixel((0,0)),(0,0,0,0))
            sat.write_status()
            self.assertEqual(sat.catalog()['times'],['20261013150000'])
            with self.assertRaises(ValueError):sat.image_path('../status')
            with self.assertRaises(FileNotFoundError):sat.image_path('20261013151000')
    def test_retention_and_error_visible(self):
        with tempfile.TemporaryDirectory() as root,patch.object(sat,'ROOT',Path(root)),patch.object(sat,'KEEP',2):
            (Path(root)/'truecolor').mkdir()
            for t in ['20261013150000','20261013151000','20261013152000']:(Path(root)/'truecolor'/f'{t}.webp').touch()
            sat.write_status('上游连接失败')
            self.assertEqual(sat.catalog()['times'],['20261013151000','20261013152000'])
            self.assertEqual(sat.catalog()['error'],'上游连接失败')
            self.assertFalse((Path(root)/'truecolor'/'20261013150000.webp').exists())

    def test_products_are_isolated(self):
        with tempfile.TemporaryDirectory() as root,patch.object(sat,'ROOT',Path(root)):
            sat.save_mosaic('20261013150000',[], 'infrared')
            sat.write_status(product='infrared')
            self.assertEqual(sat.catalog()['times'],[])
            self.assertEqual(sat.catalog('infrared')['times'],['20261013150000'])
            with self.assertRaises(ValueError):sat.image_path('20261013150000','../infrared')

    def test_display_preserves_dimensions_and_transparency(self):
        with tempfile.TemporaryDirectory() as root,patch.object(sat,'ROOT',Path(root)):
            sat.save_mosaic('20261013150000',[])
            with Image.open(sat.display_path('20261013150000','truecolor')) as image:
                self.assertEqual(image.size,(2048,2048))
                self.assertEqual(image.getpixel((0,0))[3],0)
