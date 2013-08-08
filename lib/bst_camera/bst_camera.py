import sys, os, subprocess, shutil
from time import sleep

import logging, idscam.common.syslogger

log = idscam.common.syslogger.get_syslogger('bst_camera')

NUM_DAEMON_START_RETRIES = 3
MAX_CAMERA_TRIES = 3
NUM_DAEMON_STOP_TRIES = 3
NUM_DAEMON_START_TRIES = 3

skip_compression = False

class CameraBase():
        '''CameraBase(   )

        Base camera class that can be parent to specific camera types
        '''

        def __init__(self):
                self.light_state = None
                pass

        def record_video(filename_base,
                         clip_duration,
                         video_format_params = None):
                '''CameraBase.record_video(filename_base, clip_duration, video_format_params = None)

                Not very interesting. Intended as prototype for derived classes.
                '''
                pass                 
                                                 
        def get_sensor_resoultion(self):
                '''get_sensor_resolution()

                Returns the full resolution of the sensor as tuple:
                        ( <width>, <height> )
                '''
                return self.sensor_resolution


        def set_light(self, state):
                '''set_lights(state)

                Turn lights on or off. Prototype for derived classes.

                state:  True for on, False for off
                '''


        def get_light_state(self):
                '''get_light_state()

                Returns True when light is on and False for off.
                '''
                if self.light_state == None:
                        log.warning( "Warning: Light state has not yet been set and is unknown" )
                        raise Exception

                return self.light_state
                         
class UeyeCamera(CameraBase):
        '''UeyeCamera(cam_id = None,
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
                     log_level = logging.INFO):

                log.setLevel(log_level)

                CameraBase.__init__(self)

                self.cam_id = cam_id
                self.cam_serial_number = cam_serial_number
                self.cam_device_id = cam_device_id
                self.ueye_daemon_control_script = ueye_daemon_control_script

                # Query status of ueye camera daemon
                daemon_is_running = self.daemon_call('status')

                # If not running, start ueye daemon
                if not daemon_is_running:
                        for i in range(1, NUM_DAEMON_START_RETRIES+1):
                                log.info("At camera construction, ueye daemon not running. Calling start attempt: %d" % i)
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
                        log.critical( "Error: At least one of: cam_id, cam_serial_num, or cam_device_id, must be supplied.")
                        raise Exception

                # System call for camera info request
                log.debug("Camera sending info query: %s" % camera_command)
                try:
                        p = subprocess.Popen( camera_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True )
                        rval = p.wait()
                except:
                        log.critical( "Error with camera info query system call. Exiting" )
                        sys.exit(-1)

                info_lines = p.stdout.readlines()
                error = p.stderr.read()

                log.debug( "Camera info request returned " + str(rval) + " with this info:" )
                for line in info_lines:
                        log.debug( "    " + line)
                log.debug( "and this error: " + error )

                # Checking stderr for now. idscam info call does not yet return non-zero value
                # TODO: Update to use rval instead when idscam is fixed
                if error != '':
                        log.critical("Error opening camera on info request. Probably incorrect id")
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
                        log.warning( "Error parsing resolution data from camera info. Using defaults." )
                        sensor_width = 2560
                        sensor_height = 1920
                log.info( "Camera resolution = " + str(sensor_width) + "x" + str(sensor_height) )
                self.sensor_resolution = (sensor_width, sensor_height)

                # TODO: Parse info for other camera properties?

                # Setup variables for implementing ueye daemon restarting workaround
                # Context: Daemon fails badly after too many video calls without
                # daemon restart, and also fails badly if you restart the daemon too
                # often. The workaround is to restart the daemon every X video calls
                self.num_camera_calls_since_ueye_daemon_restart = 0
                self.num_camera_calls_between_ueye_daemon_restarts = num_camera_calls_between_ueye_daemon_restarts


        def daemon_call(self, command):
                '''UeyeCamera.daemon_call( command )

                Sends a command to the ueye daemon manager script.
                
                command:   'start', 'stop', or 'status' string passed to the daemon
                                   manager script.

                Returns:   Binary value of whether daemon is running
                '''
                # Check for valid command
                  
                # TODO: Handle situation where daemon was not running and camera was not initialized
                # Otherwise we may turn on the daemon, then do a camera call before it has initialized and error out
                valid_commands = ('start', 'stop', 'status', 'force-stop')
                if not command in valid_commands:
                        log.critical( command + " is not a valid command to the ueye daemon control script" )
                        raise ValueError

                # Build command and call daemon control script
                daemon_script_call = self.ueye_daemon_control_script + " " + command
                try:
                        p = subprocess.Popen( daemon_script_call, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True )
                        rval = p.wait()
                except:
                        log.critical( "Error with ueye daemon control script system call. Exiting" )
                        sys.exit(-1)

                # Handle return value
                if rval == 0:
                        pass
                elif rval == 2 or rval == 4:
                        # Returned value signifying that it is aready running(2), or didn't terminate(4)
                        return True
                else:
                        log.critical( "Error: ueye daemon control script error. May not be installed? May not have permission? Exiting")
                        sys.exit(-1)

                response = p.stdout.read()
                error = p.stderr.read()

                log.debug( daemon_script_call + " returned: " + response )
                if error:
                        log.warning( "Daemon control script error:" + error )
                        raise RuntimeError
                
                # Parse response from call
                daemon_is_running = False
                if 'is running' in response or 'is already running' in response or 'is still running' in response:
                        daemon_is_running = True
                
                return daemon_is_running


        def restart_daemon(self):
                '''UeyeCamera.restart_daemon()

                Restart the ueye camera handling daemon.
                '''
                log.info("Restarting ueye camera daemon.")
                # First try stopping it normally
                try:
                        daemon_is_running = self.daemon_call('stop')
                except RuntimeError:
                        log.critical("Error in daemon call, can't restart")
                        raise

                if daemon_is_running:
                        # Didn't stop normally, trying a some more times with 'force-stop' option
                        for i in range(1, NUM_DAEMON_STOP_TRIES):
                                log.debug("Daemon didn't stop. Trying again with 'force-stop' option")
                                try:
                                        daemon_is_running = self.daemon_call('force-stop')
                                except RuntimeError, errmsg:
                                        log.critical("Error in daemon call: " + str(errmsg))
                                        continue
                                if not daemon_is_running:
                                        break

                # If it is still running after all of our tries, return. There is nothing more we can do.
                if daemon_is_running:
                        log.warning("Unable to stop camera daemon. Restart unsuccessful")
                        raise RuntimeError
                
                # Daemon is off, let's restart it
                for i in range(1, NUM_DAEMON_START_TRIES+1):
                        log.debug("Restarting daemon")
                        daemon_is_running = self.daemon_call('start') 
                        if daemon_is_running: 
                                log.debug("Restarted ueye camera daemon successfully.")
                                return
                
                log.warning("Unable to restart ueye camera daemon")
                raise RuntimeError
                


        def record_video(self, filename_base, clip_duration, video_format_params = None ):
                '''UeyeCamera.record_video(filename_base, clip_duration, video_format_params = None)

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
                if self.num_camera_calls_since_ueye_daemon_restart > self.num_camera_calls_between_ueye_daemon_restarts:
                        try:
                                self.restart_daemon()
                                self.num_camera_calls_since_ueye_daemon_restart = 0        
                        except RuntimeError:
                                # If there was an error with the restart don't reset the counter
                                # We'll try again next time
                                pass

                # TODO: Value check parameters

                # TODO: Looks like binned cropping is in terms of binned coordinates, but 
                # subsampled cropping is in terms of full sensor location (not subsampled) locations
                # verify and handle appropriately
                        
                # Start to build camera command with camera identifier
                command = ""
                if self.cam_device_id != None:
                        command = "idscam video --device " + str(self. cam_device_id)
                elif self.cam_id != None:
                        command = "idscam video --id " + str(self.cam_id)
                elif self.cam_serial_number != None:
                        command = "idscam video --serial " + str(self.cam_serial_number)
                else:
                        log.critical( "Error: At least one of: cam_id, cam_serial_num, or cam_device_id, must be supplied." )
                        raise ValueError

                # TODO: Check window params against image size determined by binning or subsampling

                # Add optional video parameters to command
                if video_format_params != None:
                        if video_format_params.has_key('subsampling') and video_format_params.has_key('binning'):
                                log.critical( "Error: subsampling and binning are mutually exclusive" )
                                raise ValueError
                                                                                              
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
                        elif video_format_params.has_key('cropping'):
                                command += " -ex0 " + str(video_format_params['cropping'][0])
                                command += " -ex1 " + str(video_format_params['cropping'][1])
                                command += " -ey0 " + str(video_format_params['cropping'][2])
                                command += " -ey1 " + str(video_format_params['cropping'][3])

                command += " -d " + str(clip_duration)
                command += " " + filename_base

                log.debug( "Camera command: " + command )

                # Camera call to take folder full of raw frames
                for i in range (1, MAX_CAMERA_TRIES+1):
                        self.num_camera_calls_since_ueye_daemon_restart += 1
                        rval = os.system( command )
                        if rval == 0:
                                log.debug("Video capture success")
                                break

                        if rval == 251:
                                log.warning("Camera call returned 'Camera not found' error.")
                                log.warning("It was found at camera class construction, so maybe the uEye daemon is down. Restart it.")
                                #TODO:self.restart_daemon()

                        # Camera call failed. Erase that directory so we can try again
                        sleep(1)
                        log.warning( "Error in camera video call. Returned " + str(rval) )
                        try:
                                shutil.rmtree(filename_base)
                        except OSError, (errno, errmsg):
                                if errno == 2:
                                        # Camera must not have created the directory so we don't have to delete it
                                        pass
                                else:
                                        raise 
                                
                else:
                        log.critical( "Tried camera call %d times unsuccessfully. Exiting." % i )
                        sys.exit(1)

                if skip_compression: return

                # Create video clip from raw frames, '-c' arg specs clean up of raw files
                log.debug( "Starting video compression." )
                comp_command = "raw2h264 -c " + filename_base

                try:
                        ret_val = os.system( comp_command )
                except:
                        raise
                log.debug( "Return val from compression was " + str(ret_val))



        def set_light(self, state):
                '''set_lights(state)

                Turn lights on or off.

                state:  True for on, False for off
                '''

                # Start to build camera command with camera identifier
                command = ""
                if self.cam_device_id != None:
                        command = "idscam conf --device " + str(self. cam_device_id)
                elif self.cam_id != None:
                        command = "idscam conf --id " + str(self.cam_id)
                elif self.cam_serial_number != None:
                        command = "idscam conf --serial " + str(self.cam_serial_number)
                else:
                        log.critical( "Error: At least one of: cam_id, cam_serial_num, or cam_device_id, must be supplied." )
                        raise ValueError
                
                # Finish command depending on turning on or off
                if state == True:
                        command += " --flash-on"
                        self.light_state = True
                else:
                        command += " --flash-off"
                        self.light_state = False

                # Send command to os
                rval = os.system( command )
                if rval == 0:
                        if state == True:
                                log.debug("Success turning on light")
                        else:
                                log.debug("Success turning off light")
                        return

                raise Exception
