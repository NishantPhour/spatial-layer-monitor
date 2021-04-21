from configparser import ConfigParser
import os
import shutil
import subprocess
import sys
import requests
import time
import gdal
import gdal_merge
import gdal_edit
import ogr
import geopandas as gpd
import pandas as pd
from shapely.wkt import loads
from shapely.geometry import LineString, Polygon
from sqlalchemy import create_engine
from postmarker.core import PostmarkClient
from azure.storage.blob import BlobServiceClient, BlobClient, ContainerClient

# Settings, could go to config file if neeeded
config = ConfigParser()
config.read(os.path.join(os.path.dirname(__file__),'config.cfg'))
input_image_file_ext = ".png"
output_image_file_ext = ".tif"
source_folder = "/mnt/data/dmp"
dest_folder = "/home/f2quser/Processed_Thermal_Imagery"
postgis_table = config.get('general', 'postgis_table')
azure_conn_string = config.get('general', 'azure_conn_string') 
container_name = config.get('general', 'container_name')
blob_service_client = BlobServiceClient.from_connection_string(azure_conn_string)
districts_dataset_name = config.get('general', 'districts_dataset_name')
districts_gpkg = os.path.join(os.path.dirname(__file__),districts_dataset_name)
districts_layer_name = config.get('general', 'districts_layer_name')
user = config.get('geoserver', 'user')
gs_pwd = config.get('geoserver', 'gs_pwd')

class Footprint:
    def __init__(self):
        self.as_line = None
        self.as_poly = None
        self.districts = []

def check_first_two_images_overlap(files):
    overlap = False
    if len(files) >= 2:
        first_image = gdal.Open(files[0])
        second_image = gdal.Open(files[1])
        ulx1, uly1, lrx1, lry1 = get_corners(first_image)
        ulx2, uly2, lrx2, lry2 = get_corners(second_image)
        first_image = None
        second_image = None
        # If second_image is to the right of first_image
        if ulx2 >= ulx1:
            # Is it too far right?
            if ulx2 <= lrx1: # No, not too far right
                # Is it too high?
                if uly2 >= uly1:
                    if lry2 <= uly1: # No, not too high
                        overlap = True
                # Is it too low?
                elif uly2 < uly1:
                    if uly2 >= lry1: # No, not too low
                        overlap = True
        else: # If second_image is to the left of first_image
            # Is it too far left?
            if ulx1 <= lrx2: # No, not too far right
                # Is it too high?
                if uly2 >= uly1:
                    if lry2 <= uly1: # No, not too high
                        overlap = True
                # Is it too low?
                elif uly2 < uly1:
                    if uly2 >= lry1: # No, not too low
                        overlap = True
    return overlap

def check_timediff_first_two_images(files):
    first_file = files[0]
    second_file = files[1]
    first_time = os.path.getmtime(first_file)
    second_time = os.path.getmtime(second_file)
    timediff = second_time - first_time
    return timediff

def get_corners(image):
    ulx, xres, xskew, uly, yskew, yres = image.GetGeoTransform()
    lrx = ulx + (image.RasterXSize * xres)
    lry = uly + (image.RasterYSize * yres)
    return (ulx, uly, lrx, lry)

def get_exclude_first(files):
    # Check if first photo should be excluded - need time diff btw first two > 180s AND no overlap in first two images
    overlap = check_first_two_images_overlap(files)
    timediff = check_timediff_first_two_images(files)
    if (not overlap) and timediff > 180:
        exclude_first = True
    else:
        exclude_first = False
    return exclude_first

def merge(files):
    # Merges pngs and saves output to output_image specified above
    gdal_merge_args = ["", "-o", mosaic_image, "-of", "GTiff", "-n", "0", "-a_nodata", "0"]
    for file in files:
        gdal_merge_args.append(file)
    gdal_merge.main(gdal_merge_args)
    gdal_edit_args = ["", "-a_srs", "EPSG:28350", mosaic_image]
    #gdal_edit_args = ["", "-a_srs", "EPSG:4326", mosaic_image]
    gdal_edit.main(gdal_edit_args) # creates output image in 'Processed' folder
    #push_to_azure(mosaic_image, flight_name + ".tif")

def translate_png2tif(input_png, short_file):
    # Translates png to tif
    output_tif = input_png.replace(".png", ".tif")
    tif_filename = short_file.replace(".png", ".tif")
    gdal.Translate(output_tif, input_png, outputSRS="EPSG:28350")
    blob_name = flight_name + "_images/" + tif_filename
    push_to_azure(output_tif, blob_name)
    #publish_image_on_geoserver(flight_name, tif_filename)

def push_to_azure(img_file, blob_name):
    try:
        blob_client = blob_service_client.get_blob_client(container=container_name, blob=blob_name)
        with open(img_file, "rb") as data:
            blob_client.upload_blob(data)
    except exception as e:
        print(str(e))

def create_mosaic_footprint_as_line(flight_timestamp, image, engine, footprint):
    # Get coords of diagonal corners of output raster
    working_image = gdal.Open(image)
    ulx, uly, lrx, lry = get_corners(working_image)
    working_image = None
    # Create linestring
    points = [(ulx, uly), (lrx, uly), (lrx, lry), (ulx, lry), (ulx, uly)]
    #footprint_line = LineString(points)
    footprint.as_line = LineString(points)
    footprint.as_poly = Polygon(points)
    #geom = gpd.geoseries.GeoSeries([footprint_line])
    line_geom = gpd.geoseries.GeoSeries([footprint.as_line])
    poly_geom = gpd.geoseries.GeoSeries([footprint.as_poly])
    data_dictionary = {"flight_datetime": [flight_timestamp]}
    footprint_line_layer = gpd.geodataframe.GeoDataFrame(data_dictionary, crs="EPSG:28350", geometry=line_geom).to_crs("EPSG:4326")
    footprint_line_layer.to_postgis("hotspot_flight_footprints", engine, if_exists="append")
    footprint_poly_layer = gpd.geodataframe.GeoDataFrame(data_dictionary, crs="EPSG:28350", geometry=poly_geom).to_crs("EPSG:4326")
    footprint_poly_layer.to_file(output_geopackage, layer='footprint', driver="GPKG")

def get_footprint_districts(footprint):
    districts_gdf = gpd.read_file(districts_gpkg, layer=districts_layer_name)
    footprint_gdf = gpd.read_file(output_geopackage, layer='footprint')
    for index, footprint_feature in footprint_gdf.iterrows():
        # Should only be one footprint in the layer
        footprint_geom = footprint_feature['geometry']
    for index, district in districts_gdf.iterrows():
        if footprint_geom.intersects(district['geometry']):
            footprint.districts.append(district['ADMIN_ZONE'].strip().replace(" ", "_"))

def create_img_bbox_as_poly(image):
    # Get coords of diagonal corners of output raster
    working_image = gdal.Open(image)
    ulx, uly, lrx, lry = get_corners(working_image)
    working_image = None
    # Create linestring
    points = [(ulx, uly), (lrx, uly), (lrx, lry), (ulx, lry)]
    poly = Polygon(points)
    return str(poly)

def create_img_bounding_boxes(files, raw_img_folder):
    bbox_polys = []
    files_columns = []
    for file in files:
        filename = os.path.basename(file)
        #short_file = os.path.join(raw_img_folder, filename) files_columns.append([file, short_file])
        files_columns.append([file, filename])
        poly = create_img_bbox_as_poly(file)
        bbox_polys.append(poly)
    crs = "EPSG:28350"
    geom = gpd.geoseries.GeoSeries([loads(poly) for poly in bbox_polys])
    geom.crs = crs
    bboxes = gpd.geodataframe.GeoDataFrame(files_columns, crs=crs, geometry=geom, columns=['file', 'short_file'])
    bboxes = bboxes.to_crs('EPSG:4326')
    return bboxes 

def create_boundaries_and_centroids(flight_timestamp, kml_boundaries_file, bboxes, engine):
    all_images_with_hotspots = []
    try:
        # NB bboxes is a set of bounding boxes for each image (excluding the first, if exclude_first is True) gpd.io.file.fiona.drvsupport.supported_drivers['KML'] = 'rw' # Enables 
        # fiona KML driver
        gpd.io.file.fiona.drvsupport.supported_drivers['LIBKML'] = 'rw' # Enables fiona KML driver
        kml_boundaries = gpd.read_file(kml_boundaries_file)
        kml_boundaries['geometry'] = kml_boundaries.geometry.buffer(0)
        boundary_geometries = []
        try:
            boundary_geometries = [geom for geom in kml_boundaries.unary_union.geoms]
        except:
            return []
        included_geometries = []
        centroid_geometries = []
        images_column = []
        flight_datetime_column = []
        hotspot_no_column = []
        i = 1
        for geom in boundary_geometries:
            envelope = geom.envelope
            images = []
            for index, row in bboxes.iterrows():
                box = row['geometry']
                file = row['file']
                short_file = row['short_file']
                if envelope.intersects(box):
                    images.append(short_file)
                    if short_file not in all_images_with_hotspots:
                        all_images_with_hotspots.append(short_file)
            if len(images) > 0:
                included_geometries.append(geom)
                centroid_geometries.append(geom.centroid)
                images_column.append(str(images)[1:-1].replace("'", "").replace(".png", ""))
                flight_datetime_column.append(flight_timestamp)
                hotspot_no_column.append(i)
                i += 1
        data_dictionary = {"flight_datetime": flight_datetime_column, "hotspot_no": hotspot_no_column, "images": images_column}
        crs="EPSG:4283"
        boundaries = gpd.geodataframe.GeoDataFrame(data_dictionary, crs=crs, geometry=included_geometries)
        boundaries = boundaries.to_crs('EPSG:4326')
        boundaries.to_file(output_geopackage, layer='boundaries', driver="GPKG")
        boundaries.to_postgis("hotspot_boundaries", engine, if_exists="append")
        centroids = gpd.geodataframe.GeoDataFrame(data_dictionary, crs=crs, geometry=centroid_geometries)
        centroids = centroids.to_crs('EPSG:4326')
        centroids.to_file(output_geopackage, layer='centroids', driver="GPKG")
        centroids.to_postgis("hotspot_centroids", engine, if_exists="append")
    except Exception as e:
        print(e)
    finally:
        return sorted(all_images_with_hotspots)

def send_notification_emails(flight_name, success, msg, districts=[]):
    postmark = PostmarkClient(server_token=config.get('general', 'server_token'))
    recipients = config.get('emails', 'always_email')
    if not success:
        postmark.emails.send(
            From='patrick.maslen@dbca.wa.gov.au',
            To=recipients,
            Subject='New Thermal Image data FAILED to complete processing',
            HtmlBody='Automated email advising that a new dataset,' + flight_name + ', has arrived but has not been successfully processed on kens-therm-001.<br>' + msg
        )
    else:
        for district in districts:
            recipients += ', ' + config.get('emails', district)
        postmark.emails.send(
                From='patrick.maslen@dbca.wa.gov.au',
                To=recipients,
                Subject='New Thermal Image data available',
                HtmlBody='Automated email advising that a new dataset,' + flight_name + ', has arrived and has been successfully processed; it can be viewed in SSS.<br>' + msg)

def publish_image_on_geoserver(flight_name, image_name=None):
    flight_timestamp = flight_name.replace("FireFlight_", "")
    headers = {'Content-type': 'application/xml'}
    file_url_base = 'file:///rclone-mounts/thermalimaging-flightmosaics/'
    gs_url_base = 'https://hotspots.dbca.wa.gov.au/geoserver/rest/workspaces/hotspots/coveragestores/'
    if image_name is None:
        gs_layer_url = gs_url_base + flight_name + '.tif/coverages'
    else:
        gs_layer_url = gs_url_base + flight_timestamp + '_img_' + image_name + '/coverages'
    # Create data store on geoserver
    if image_name is None:
        store_data = '<coverageStore><name>{flight_name}.tif</name><workspace>hotspots</workspace><enabled>true</enabled><type>GeoTIFF</type><url>{file_url_base}{flight_name}.tif</url></coverageStore>'.format(flight_name=flight_name, file_url_base=file_url_base)
    else:
        store_data = '<coverageStore><name>{flight_timestamp}_img_{image}</name><workspace>hotspots</workspace><enabled>true</enabled><type>GeoTIFF</type><url>{file_url_base}{flight_name}_images/{image_name}</url></coverageStore>'.format(flight_name=flight_name, flight_timestamp=flight_timestamp, file_url_base=file_url_base, image=image_name, image_name=image_name)
    response = requests.post(gs_url_base, headers=headers, data=store_data, auth=(user, gs_pwd))
    #if response.status_code == 201:
    #   print('Great success!') Create mosaic image layer
    if image_name is None:
        layer_data = '<coverage><name>{flight_name}</name><title>{flight_name}</title><srs>EPSG:28350</srs></coverage>'.format(flight_name=flight_name)
    else:
        layer_data = '<coverage><name>{flight_timestamp}_img_{image}</name><title>{flight_timestamp}_img_{image}</title><srs>EPSG:28350</srs></coverage>'.format(flight_timestamp=flight_timestamp, image=image_name[:-4])
    response = requests.post(gs_layer_url, headers=headers, data=layer_data, auth=(user, gs_pwd))
    #if response.status_code == 201:
    #   print('Great success!')


##############################################################################
# MAIN PROCESS In response to new zipfile in source folder, create destination folder
flight_name = sys.argv[1]
flight_timestamp = flight_name.replace("FireFlight_", "")
main_folder = os.path.join(dest_folder, flight_name)
# Set filepaths and a couple of other settings
raw_img_folder = os.path.join(main_folder, "PNGs/CAMERA1")
output_folder = os.path.join(main_folder, "Processed")
mosaic_image = os.path.join(output_folder, flight_name + "_mosaic" + output_image_file_ext)
footprint = Footprint()
kml_boundaries_folder = os.path.join(main_folder, "KML Boundaries/CAMERA1")
kml_boundaries_file =""
for filename in os.listdir(kml_boundaries_folder):
    if "supermosaic_" in filename.lower() and filename.lower().endswith("bnd.kml"):
        kml_boundaries_file = os.path.join(kml_boundaries_folder, filename)
        break
if kml_boundaries_file == "":
    for filename in os.listdir(kml_boundaries_folder):
        if filename.lower() == "mosaic_0_0_bnd.kml":
            kml_boundaries_file = os.path.join(kml_boundaries_folder, filename)
            break
if kml_boundaries_file == "":
    send_notification_emails(flight_name, False, "No file named *SuperMosaic*BND.kml found in KML Boundaries folder")
else:
    engine = create_engine(postgis_table)
    output_geopackage = os.path.join(output_folder, "output.gpkg")
    exclude_first = None
    files = [os.path.join(raw_img_folder, f) for f in os.listdir(raw_img_folder) if f.endswith(input_image_file_ext)]
    files.sort()
    exclude_first = get_exclude_first(files)
    if exclude_first:
        files.remove(files[0])
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
    success = True
    global msg
    msg = ""
    all_images_with_hotspots = []
    try:
        merge(files)
        msg += "<br>Mosaic produced on kens-therm-001 OK"
        print("Mosaic produced on kens-therm-001 OK")
    except:
        success = False
        msg += "<br>Mosaic production on kens-therm-001 failed"
        print("Mosaic production on kens-therm-001 failed")
    time.sleep(60)
    mosaic_pushed_to_azure = False
    try:
        push_to_azure(mosaic_image, flight_name + ".tif")
        msg += "<br>Mosaic pushed to Azure OK"
        print("Mosaic pushed to Azure OK")
        mosaic_pushed_to_azure = True
    except:
        msg += "<br>Mosaic push to Azure failed"
        print("Mosaic push to Azure failed")
    try:
        create_mosaic_footprint_as_line(flight_timestamp, mosaic_image, engine, footprint)
        # NB this populates footprint.as_line and footprint.as_poly
        msg += "<br>Footprint produced and pushed to PostGIS OK"
        print("Footprint produced and pushed to PostGIS OK")
    except:
        success = False
        msg += "<br>Footprint production or push to PostGIS failed"
        print("Footprint production or push to PostGIS failed")
    try:
        get_footprint_districts(footprint)
        msg += "<br>Footprint lies in district(s) " + str(footprint.districts)
        print("Footprint lies in district(s) " + str(footprint.districts))
    except:
        success = False
        msg += "<br>Footprint district(s) not found"
        print("Footprint district(s) not found")
    try:
        bboxes = create_img_bounding_boxes(files, raw_img_folder)
        msg += "<br>Bounding box creation for images OK"
        print("Bounding box creation for images OK")
    except:
        success = False
        msg += "<br>Bounding box creation for images failed"
        print("Bounding box creation for images failed")
    try:
        all_images_with_hotspots = create_boundaries_and_centroids(flight_timestamp, kml_boundaries_file, bboxes, engine) # e.g. = ['000039.png', '000040.png', ... , '000106.png']
        if all_images_with_hotspots == []:
            msg += "<br>NO HOTSPOTS FOUND!!!"
            print("NO HOTSPOTS FOUND!!!")
            #success = False
        else:
            msg += "<br>Boundaries and centroids creation and push to PostGIS OK"
            print("Boundaries and centroids creation  and push to PostGIS OK")
    except:
        success = False
        msg += "<br>Boundaries and centroids creation or push to PostGIS failed"
        print("Boundaries and centroids creation or push to PostGIS failed")
    try:
        if len(all_images_with_hotspots) > 0:
            for img in all_images_with_hotspots:
                full_path = os.path.join(raw_img_folder, img)
                translate_png2tif(full_path, img)
            msg += "<br>Production of tif images OK"
            print("Production of tif images OK")
    except:
        msg += "<br>Production of tif images failed"
        print("Production of tif images failed")
    # A cron job runs in Rancher every 5 min to update the file storage for geoserver; also allow extra time for processing - 10 min; later reduced to 1min
    time.sleep(60)
    try:
        if mosaic_pushed_to_azure:
            publish_image_on_geoserver(flight_name)
            msg += "<br>Mosaic published on geoserver OK"
            print("Mosaic published on geoserver OK")
        else:
            msg += "<br>Mosaic could not be published on geoserver!!!"
            print("Mosaic could not be published on geoserver!!!")
        for img in all_images_with_hotspots:
            img = img.replace(".png", ".tif")
            publish_image_on_geoserver(flight_name, img)
    except:
        success = False
        msg += "<br>Mosaic publishing on geoserver failed"
        print("Mosaic publishing on geoserver failed")
    #print(msg)
    send_notification_emails(flight_name, success, msg, footprint.districts)
