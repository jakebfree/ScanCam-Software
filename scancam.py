import argparse, sys
from time import sleep, time, gmtime
import thread
import pickle
import os
try:
    import argparse
except ImportError, err:
    syslogger.critical("Failed to import argparse")
    if version_info < (2, 7):
        syslogger.critical("your are running an older version of Python. argparse was added in Python 2.7 please add library manually")
        exit(1)
    else:
        raise err

from serial_connection import *
from linear_slides import *
from rotary_stages import *
from scan_building_tools import *






DEFAULT_STAGE_ACTION_TIMEOUT = 60       # seconds
MAX_CLIP_LENGTH = 60                    # seconds
MAX_Z_MOVE_SPEED = 3.0                  # mm/second
CAMERA_STARTUP_TIME = 0.0               # seconds

min_period_bt_scans = 1                 # in minutes
verbose = True
home_on_start = True
just_one_scan = True
skip_video = True
comm_device = "COM3"
scan_filename = "/etc/

video_location = "/home/freemajb/data/scancam_proto_videos/"



# HACK to set the scan before we import from file
xyz_scan = proto_xyz_scan 
#xyz_scan = model_xyz_scan




def wait_for_devices_to_complete_actions(devices, timeout_secs):
        '''wait_for_devices_to_complete_actions(devices, timeout_secs)

        For each device in devices, wait until .in_action() returns False
        '''
        try:
                for device in devices:
                        device.wait_for_action_to_complete( timeout_secs )
        except zaber_device.DeviceTimeoutError, device_id:
                # If one device times out, stop all of them
                for device in devices:
                        device.stop()
                raise



def scan_action(xyz_scan, verbosity):

        scan_point_num = 0
        for point in xtz_scan:

                scan_point_num += 1
                if verbose: print "Step", scan_point_num, point

                # Enqueue scan point move commands
                #x_stage.set_target_speed_in_units( 6.0 )
                x_stage.move_absolute( point['X'] )
                theta_stage.move_absolute( point['theta'] )
                if point.has_key('z0'):
                        z_stage.move_absolute( point['z0'] )

                        # Set z-axis speed to standard moderately fast value. It may have been set to a
                        # different value during an image-through-depth sequence
                        z_stage.set_target_speed_in_units( STANDARD_Z_SPEED, 'A-series' )
                        z_stage.step()

                # Step to next queued scan point for all axes
                for stage in stages:
                        stage.step()
                try:
                        wait_for_devices_to_complete_actions( stages, DEFAULT_STAGE_ACTION_TIMEOUT )
                except zaber_device.DeviceTimeoutError, device_id:
                        print "Device", device_id, "timed out during move for scan point", scan_point_num
                        raise

                # If this scan point has no time value, there is no video to record
                if not point.has_key('t'):
                        if verbose: print "Point has no time value. Skipping z1 and video"
                        continue
                
                clip_duration = int(point['t'])
                
                # If there is a second z-axis value, start the move to it as we start the video clip
                # The clip will progress through the depth of the move. If t = 0 it is for an image so skip z1
                if point.has_key('z1') and point['t'] != float(0.0):
                        # The move from z0 to z1 should take the same amount of time as the video clip duration
                        # But, the camera may require a little warm-up time from system call to the first frame
                        # We'll add a small buffer of time to the z-axis move so that even if the move and clip
                        # don't start together, at least they will end together.
                        try:
                                target_z_speed = abs(point['z1']-point['z0']) / (float(point['t'])+CAMERA_STARTUP_TIME)

                                if target_z_speed > MAX_Z_MOVE_SPEED:
                                        # Calculate clip duration, rounding up to next int
                                        clip_duration = ceil(abs(point['z1']-point['z0']) / MAX_Z_MOVE_SPEED - CAMERA_STARTUP_TIME)
                                        print target_z_speed, "is too fast. Setting to max speed:", MAX_Z_MOVE_SPEED, \
                                                              "And extending clip duration to:", clip_duration
                                        target_z_speed = MAX_Z_MOVE_SPEED
                                # TODO: fix set_target_speed_in_units call to be type agnostic
                                z_stage.set_target_speed_in_units( target_z_speed, 'A-series' )

                                z_stage.move_absolute( point['z1'] )
                                z_stage.step()
                        except ZeroDivisionError:
                                print "Error: cannot have move from z0 to z1 in 0 seconds. Skipping z1"
                
                # TODO: Looks like binned cropping is in terms of binned coordinates, but 
                # subsampled cropping is in terms of full sensor location (not subsampled) locations
                # verify and handle appropriately
                
                # Start raw video recording
                camera_id = 1
                subsampling = 3
                binning = 0
                x0 = 320
                x1 = 2240
                y0 = 0
                y1 = 1920

                # Build video file target basename in the format:
                #       <payload>_<scan definition ID>_<scan point ID>.<YYYY-MM-DD_HH-mm-SS>.h264
                t = gmtime( time() )
                t_str = "%04d-%02d-%02d_%02d-%02d-%02d" % (t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec)
                if point.has_key('point-id'):
                        filename_base = "proto_built-in-scan_" + point['point-id'] + '.' + t_str
                else:
                        filename_base = "proto_built-in-scan_" + str(scan_point_num) + '.' + t_str

                # Build camera command
                command = "idscam video --id " + str(camera_id)
                
                if subsampling:
                        command += " -s " + str(subsampling)
                if binning:
                        command += " -b " + str(binning)
                command += " -d " + str(clip_duration)
                command += " -x0 %d -ex0 %d -x1 %d -ex1 %d -y0 %d -ey0 %d -y1 %d -ey1 %d" % (x0,x0,x1,x1,y0,y0,y1,y1)
                command += " " + filename_base

                if verbose: 
                        print "Camera command:", command

                if skip_video:
                        print "Skipping video. Sleeping", clip_duration, "instead"
                        sleep(clip_duration)
                        continue
                
               # System call to camera
                try:
                        if verbose: print "System call to camera."
                        os.system(command)
                except KeyboardInterrupt:
                        raise        
                except:
                        raise

                # Create video clip from raw frames, -c arg specs clean up of raw files
                if verbose: print "Starting video compression."
                comp_command = "raw2h264 -c " + filename_base

                try:
                        ret_val = os.system( comp_command )
                except:
                        raise
                if verbose: print "Return val from compression was", ret_val

                # Assure that the last z-axis move was completed
                try:
                        z_stage.wait_for_action_to_complete( DEFAULT_STAGE_ACTION_TIMEOUT )
                except zaber_device.DeviceTimeoutError, device_id:
                        print "Device", device_id, "timed out during second z move on scan point", scan_point_num
                        raise




if __name__ == '__main__':

        # open file and unpickle the scan

        # Convert from xyz coordinates to x-theta-z coord
        try:
                xtz_scan = xyz_scan_2_xthetaz_scan( xyz_scan, verbosity = verbose_for_coord_trans )
        except SyntaxError:
                print "Unable to translate xyz scan points to x-theta-z. Exiting."
                sys.exit(0)


        # parse arguments
        # scancam [OPTION]... [SCANFILE]...
        #
        # -p, --minimum-period in minutes



        # scan is a list of scanpoints represented as dictionaries with the keys:
        #	x	x-axis target location in mm
        #	theta	rotary stage target location in deg
        #	z	z-axis target location in mm
        #	t	time in seconds to record video



        # Create serial connection
        # TODO: handle exceptions
        ser = serial_connection(comm_device)

        # TODO Flush serial port and anything else necessary to have clean comm start


        # Instantiate the axes
        # From T-LSM200A specs: mm_per_rev = .047625 um/microstep * 64 microstep/step * 200 steps/rev * .001 mm/um = .6096 mm/rev
        x_stage = linear_slide(ser, 1, mm_per_rev = .6096, verbose = verbose, run_mode = STEP)

        # From T-RS60A specs: .000234375 deg/microstep * 64 microsteps/step = .015 deg/step
        theta_stage = rotary_stage(ser, 2, deg_per_step = .015, verbose = verbose, run_mode = STEP)

        # From LSA10A-T4 specs: mm_per_rev = .3048 mm/rev
        #z_stage = linear_slide(ser, 3, mm_per_rev = .3048, verbose = verbose, run_mode = STEP)

        stages = [ x_stage, theta_stage ]

        # Put everything in try statement so that we can finally close the serial port on any error
        try:
                # Open serial connection
                print "Opening serial connection in thread"
                thread.start_new_thread( ser.open, ())


                # TODO: Send command to reset stages to defaults
                # TODO: Read in the default target speed for z so we can use it for z0 moves

                
                # Home all axes
                if home_on_start:
                        for stage in stages:
                                stage.home()
                                stage.step()

                        try:
                                wait_for_devices_to_complete_actions( stages, DEFAULT_STAGE_ACTION_TIMEOUT )
                        except zaber_device.DeviceTimeoutError, device_id:
                                print "Device", device_id, "timed out during intial homing"
                                raise
                        
                # Loop and continually scan with a timed periodicity
                completed_scans = 0
                last_scan_start_time = 0
                while (1):

                        # Once a second, check to see if it's time to start a new scan
                        if time() <= last_scan_start_time + min_period_bt_scans*60.0:
                                sleep(1)
                                continue
                        last_scan_start_time = time()
                        
                               
                        # Walk through scan
                        if verbose: print "Starting scan number", completed_scans + 1
                        scan_action(xyz_scan, verbosity=verbose)
  
                        completed_scans += 1

                        if( just_one_scan == True ):
                                break
                        
        except KeyboardInterrupt:
                print "Completed", completed_scans, "scans."


        finally:
                for stage in stages:
                        stage.stop

                # Close serial connection before final exit
                print "Closing serial connection"
                ser.close()
                print "Connection closed"

