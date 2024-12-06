

# Third-Party
import os
import logging
import subprocess
from datetime import datetime
# Local
from govapp import settings

logger = logging.getLogger(__name__)

class ImportsProcessor():

    def __init__(self, source_path, dest_path):
        self.path = source_path
        self.dest_path = dest_path

    def process_files(self):
        logger.info(f"Processing pending Imports from : {self.path}")
        
        current_datetime = datetime.now().astimezone()
        seen_datetime = datetime.strftime(current_datetime, '%Y-%m-%d %H:%M:%S')
        BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(settings.__file__))))
        try:
            if (not os.path.isabs(self.path)):
                self.path = os.path.join(BASE_DIR, self.path)
                
            for entry in os.scandir(self.path):
                filename = entry.name
                current_datetime = datetime.now().astimezone()
                seen_datetime = datetime.strftime(current_datetime, '%Y-%m-%d %H:%M:%S')

                # log watch
                logger.info (seen_datetime+" File to be processed: "+ str(entry.path))   

                two_char_extension = str(filename)[-3:]
                three_char_extension = str(filename)[-4:]
                if two_char_extension == '.7z' or three_char_extension == '.zip':
                    try:
                        script_path = os.path.join(BASE_DIR, 'thermalimageprocessing/thermal_image_processing.sh')
                        dest_path = os.path.join(BASE_DIR, self.dest_path)
                        logger.info("Destination folder "+str(dest_path))
                        result = subprocess.run(["/bin/bash", script_path, entry.path, dest_path], capture_output=True, text=True, check=True)
                        logger.info(result)
                    except Exception as e:
                        logger.info (e)
                        logger.info (e.output)
        except Exception as e:
            logger.error(e)