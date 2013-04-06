import sys, os, subprocess, shutil
from time import sleep


NUM_DAEMON_START_RETRIES = 3
MAX_CAMERA_TRIES = 3

verbose = True
skip_compression = False

class camera_base():
        '''camera_base(   )

        Base camera class that can be parent to specific camera types
        '''

        def __init__():
                pass

        def record_video(filename_base,
                         clip_duration,
                         video_format_params = None):
                '''camera_base.record_video(filename_base, clip_duration, video_format_params = None)

                Not very interesting. Intended as prototype for derived classes.
                '''
                pass                 
                                                 
        def get_sensor_resoultion(self):
                '''get_sensor_resolution()

                Returns the full resolution of the sensor as tuple:
                        ( <width>, <height> )
                '''
                return self.sensor_resolution

                         
class ueye_camera(camera_base):
        '''ueye_camera(cam_id = None,
                     cam_serial_num = None,
                     cam_device_id = None,
                     num_camera_calls_between_ueye_daemon_restarts = 50,
                     ueye_daemon_control_script = "/etc/init.d/ueyeusbdrc",
                     verbosity = False)

        Class representing the uEye family of cameras from IDS. Uses system
        calls to idscam to implement video clips

        cam_id:

        cam_serial_num:

        cam_device_id:

        num_camera_calls_between_ueye_daemon_restarts:  Number of system calls
                        to ueye camera before restarting its flakey daemon

        verbosity:      Verbosity
        '''

        def __init__(self,
                     cam_id = None,
                     cam_serial_number = None,
                     cam_device_id = None,
                     num_camera_calls_between_ueye_daemon_restarts = 50,
                     ueye_daemon_control_script = "/etc/init.d/ueyeusbdrc",
                     verbose = False):

                self.cam_id = cam_id
                self.cam_serial_number = cam_serial_number
                self.cam_device_id = cam_device_id
                self.ueye_daemon_control_script = ueye_daemon_control_script

                # Query status of ueye camera daemon
                daemon_is_running = self.daemon_call('status')

                # If not running, start ueye daemon
                if not daemon_is_running:
                        for i in range(1, NUM_DAEMON_START_RETRIES+1):
                                if verbose: print "At camera construction, ueye daemon not running. Calling start attempt:", i
                                is_running = self.daemon_call('start')
                                if is_running:
                                        break
                                sleep(1)
                                
                
                # Build info request command for camera
                if cam_device_id != None:
                        camera_command = "idscam info --device " + str(cam_device_id)
                elif cam_id != None:
                        camera_command = "idscam info --id " + str(cam_id)
                elif cam_serial_number != None:
                        camera_command = "idscam info --serial " + str(cam_serial_number)
                else:
                        print "Error: At least one of: cam_id, cam_serial_num, or cam_device_id, must be supplied."
                        raise Exception

                # System call for camera info request
                if verbose: print "Camera sending info query:", camera_command
                try:
                        p = subprocess.Popen( camera_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True )
                        rval = p.wait()
                except:
                        print "Error with camera info query system call. Exiting"
                        sys.exit(-1)

                info_lines = p.stdout.readlines()
                error = p.stderr.read()
                if verbose: 
                        print "Camera info request returned", rval, "with this info:"
                        for line in info_lines:
                                print line
                        print "and these errors:"
                        print error
                # Checking stderr for now. idscam info call does not yet return non-zero value
                # TODO: Update to use rval instead when idscam is fixed
                if error != '':
                        print "Error opening camera on info request. Probably incorrect id"
                        raise Exception

                # Parse resolution data from returned camera info
                sensor_width = 0
                sensor_height = 0
                for line in info_lines:
                        if 'Max Width' in line:
                                sensor_width = line.split()[-1]
                        if 'Max Height' in line:
                                sensor_height = line.split()[-1]
                if not sensor_width or not sensor_height:
                        print "Error parsing resolution data from camera info. Using defaults."
                        sensor_width = 2560
                        sensor_height = 1920
                if verbose: print "Camera resolution =", sensor_width, "x", sensor_height
                self.sensor_resolution = (sensor_width, sensor_height)

                # TODO: Parse info for other camera properties?

                # Setup variables for implementing ueye daemon restarting workaround
                # Context: Daemon fails badly after too many video calls without
                # daemon restart, and also fails badly if you restart the daemon too
                # often. The workaround is to restart the daemon every X video calls
                self.num_camera_calls_since_ueye_daemon_restart = 0
                self.num_camera_calls_between_ueye_daemon_restarts = num_camera_calls_between_ueye_daemon_restarts


        def daemon_call(self, command):
                '''ueye_camera.daemon_call( command )

                Sends a command to the ueye daemon manager script.
                
                command:   'start', 'stop', or 'status' string passed to the daemon
                                   manager script.

                Returns:   Binary value of whether daemon is running
                '''
                # Check for valid command
                valid_commands = ('start', 'stop', 'status')
                if not command in valid_commands:
                        print "Error:", command, "is not a valid command to the ueye daemon control script"
                        raise ValueError

                # Build command and call daemon control script
                daemon_script_call = self.ueye_daemon_control_script + " " + command
                try:
                        p = subprocess.Popen( daemon_script_call, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True )
                        rval = p.wait()
                except:
                        print "Error with ueye daemon control script system call. Exiting"
                        sys.exit(-1)
                if rval != 0:
                        print "Error: ueye daemon control script error. May not be installed? Exiting"
                        sys.exit(-1)
                response = p.stdout.read()
                error = p.stderr.read()
                if verbose:
                        print daemon_script_call, "returned:", response
                        if error:
                                print "Error response:", error
                
                # Parse response from call
                daemon_is_running = False
                if 'is running' in response or 'is already running' in response or 'is still running' in response:
                        daemon_is_running = True
                
                return daemon_is_running

                
        def record_video(self, filename_base, clip_duration, video_format_params = None ):
                '''ueye_camera.record_video(filename_base, clip_duration, video_format_params = None)

                Record a video clip and compress to h264 file.

                filename_base:  Name of video clip file to create. It is appended
                                with ".h226" on actual file.

                clip_duration:  Integer value in seconds of video clip duration.

                video_format_params:  Dictionary of video format parameters to apply
                                to the video. Acceptable keys are:

                        'subsampling':    Integer representing the resolution reduction factor
                                achieved by the camera only reading a subset of the
                                sensor's pixels. Thus the total field of view of the
                                camera is maintained while decreasing the resolution of
                                the images. The factor is applied in both horiz and vert
                                directions. E.g. a 2560x1920 with 3x subsampling
                                produces an image that is 854x640. Available settings
                                depend on the camera model. Mutually exclusive with
                                binning.

                        'binning'        Integer representing the resolution reduction factor
                                achieved by the camera returning an averaged vallue for
                                a small groups of pixels. Thus the total field of view
                                of the camera is maintained while decreasing the
                                resolution of the images. The factor is applied in both
                                horiz and vert directions. E.g. a 2560x1920 sensor with
                                2x subsampling produces an image that is 1280x960.
                                Available settings depend on the camera model. Mutually
                                exclusive with subsampling.

                        'cropping'       Tuple of integers conataining the borders of the area to be cropped
                                (<left edge>, <right edge>, <top edge>, <bottom edge>)
                                Pixel locations are represented in terms of the image, not the sensor.
                                For example: When using binning, the cropped should be
                                specified in terms of the smaller binned resolution.

                        'exposure_window'  Region of the sensor to use for light intensity
                                measurement to determine exposure. Value is a specified
                                as a tuple: (<left edge>, <right edge>, <top edge>,
                                <bottom edge>) where each component is an integer value
                                representing the pixel location of the window's edge.
                                Pixel locations are represented in terms of the image,
                                not the sensor. For example: When using binning, the
                                cropped should be specified in terms of the smaller
                                binned resolution.

                Video is taken at fastest frame rate available given other video
                parameters.
                '''

                # TODO: Check to see if it is time for a ueye daemon restart

                # TODO: Value check parameters

                # Start to build camera command with camera identifier
                command = ""
                if self.cam_device_id != None:
                        command = "idscam video --device " + str(self. cam_device_id)
                elif self.cam_id != None:
                        command = "idscam video --id " + str(self.cam_id)
                elif self.cam_serial_number != None:
                        command = "idscam video --serial " + str(self.cam_serial_number)
                else:
                        print "Error: At least one of: cam_id, cam_serial_num, or cam_device_id, must be supplied."
                        raise ValueError

                # TODO: Check window params against image size determined by binning or subsampling

                if video_format_params.has_key('subsampling') and video_format_params.has_key('binning'):
                        print "Error: subsampling and binning are mutually exclusive"
                        raise ValueError
                                                                                              
                # Add optional video parameters to command
                if video_format_params != None:
                        if video_format_params.has_key('subsampling'):
                                command += " -s " + str(video_format_params['subsampling'])
                                
                        if video_format_params.has_key('binning'):
                                command += " -b " + str(video_format_params['binning'])

                        if video_format_params.has_key('cropping'):
                                command += " -x0 " + str(video_format_params['cropping'][0])
                                command += " -x1 " + str(video_format_params['cropping'][1])
                                command += " -y0 " + str(video_format_params['cropping'][2])
                                command += " -y1 " + str(video_format_params['cropping'][3])
                                   
                        if video_format_params.has_key('exposure_window'):
                                command += " -ex0 " + str(video_format_params['exposure_window'][0])
                                command += " -ex1 " + str(video_format_params['exposure_window'][1])
                                command += " -ey0 " + str(video_format_params['exposure_window'][2])
                                command += " -ey1 " + str(video_format_params['exposure_window'][3])
                        # If exposure window not explicitly spec'd, make it same as the cropping
                        else:
                                command += " -ex0 " + str(video_format_params['cropping'][0])
                                command += " -ex1 " + str(video_format_params['cropping'][1])
                                command += " -ey0 " + str(video_format_params['cropping'][2])
                                command += " -ey1 " + str(video_format_params['cropping'][3])

                command += " -d " + str(clip_duration)
                command += " " + filename_base

                if verbose: 
                        print "Camera command:", command

                # Camera call to take folder full of raw frames
                for i in range (1, MAX_CAMERA_TRIES+1):
                        self.num_camera_calls_since_ueye_daemon_restart += 1
                        rval = os.system( command )
                        if rval == 0:
                                if verbose: print "Video capture success"
                                break

                        if rval == 251:
                                print "Camera call returned 'Camera not found' error."
                                print "It was found at camera class construction, so maybe the uEye daemon is down. Restart it."
                                #self.restart_daemon()

                        # Camera call failed. Erase that directory so we can try again
                        sleep(1)
                        print "Error in camera video call. Returned", rval
                        try:
                                shutil.rmtree(filename_base)
                        except OSError, (errno, errmsg):
                                if errno == 2:
                                        # Camera must not have created the directory so we don't have to delete it
                                        pass
                                else:
                                        raise 
                                
                else:
                        print "Tried camera call", i, "times unsuccessfully. Exiting."
                        sys.exit(1)

                if skip_compression: return

                # Create video clip from raw frames, '-c' arg specs clean up of raw files
                if verbose: print "Starting video compression."
                comp_command = "raw2h264 -c " + filename_base

                try:
                        ret_val = os.system( comp_command )
                except:
                        raise
                if verbose: print "Return val from compression was", ret_val

