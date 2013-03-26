import argparse, sys
from serial_connection import *
from linear_slides import *
from rotary_stages import *
from time import sleep, time, gmtime
import thread
import pickle
from math import *
import os



#
#
#
#
#
# There are three types of time values for a scan point.
#       no 't' key:     Skip z1 move and all video calls. This may be used for intermediate
#                       scan points that don't require video
#       t = 0:          Place-holder for taking an image instead of video.
#       t > 0:          Video clip duration. Also used to determine z-speed during move to z1
#
#
#
#
#
#




MAX_STAGE_ACTION_TIMEOUT = 100          # seconds
DEFAULT_STAGE_ACTION_TIMEOUT = 50       # seconds
MAX_CLIP_LENGTH = 60                    # seconds
MAX_Z_MOVE_SPEED = 3.0                  # mm/second
CAMERA_STARTUP_TIME = 0.0               # seconds

min_period_bt_scans = 1                 # in minutes

verbose = True
home_on_start = False
just_one_scan = True
skip_video = True
verbose_for_coord_trans = False
verbose_for_scan_build = False
comm_device = "COM3"

video_location = "/home/freemajb/data/scancam_proto_videos/"



def wait_for_actions_to_complete( devices, timeout_secs ):
        if timeout_secs > MAX_STAGE_ACTION_TIMEOUT:
                #TODO: raise Exception
                return
        
        counter = 0
        while (1):
                devices_in_action = []
                for device in devices:
                        if device.in_action():
                                devices_in_action.append( device.get_id() )
                if not devices_in_action:
                        break

                sleep(1)
                counter += 1
                if counter > timeout_secs:
                        print "Wait for actions to complete: timeout after %d secs" % counter
                        # TODO: Send stop signal in case we have a ridiculously low speed and it hasn't got there yet
                        break



def xtz2xyz( xtz, arm_length = 55.0 ):
        '''xthetaz2xyz( xtz )

        Convert a {'x':<>, 'theta':<> } point to a { 'x':<> 'y':<>} point
        If the passed dict has z0, z1, and/or t keys, the values are copied over
        '''
        
        print "xtz =", xtz

        xyz = {}
        xyz['x'] = xtz['x'] - sin( radians(xtz['theta']) ) * arm_length
        xyz['y'] = -cos( radians(xtz['theta']) ) * arm_length
        if xtz.has_key('z0'):
                xyz['z0'] = xtz['z0']
        if xtz.has_key('z1'):
                xyz['z1'] = xtz['z1']
        if xtz.has_key('t'):
                xyz['t'] = xtz['t']

        return xyz

                

def xyz_scan_2_xthetaz_scan ( xyz_scan, arm_length = 52.5, min_X = 0.0, max_X = 176.0, verbosity = 0 ):
        '''
        xyz2xtz ( xyz_scan, arm_length, min_X, max_X )

        Use physical geometry to translate from a cartesian xyz coord scan to the one
        described by the x, theta, z where theta is the angle of the rotary axis
        '''
        
        xthetaz_scan = []
        xt_keys = ( 'x', 'theta', 'z0', 'z1' )
        used_negative_last_time = False
        for xyz in xyz_scan:
                x = xyz['x']
                y = xyz['y']

                # Calculate X-theta Coordinates
                # There are regions (closer to X=0) where the arm can't swing to the correct y value
                # without swinging back toward the negative X direction. The angle required for the
                # same y value but swinging back is the negative of the angle. The rotary stage cannot
                # handle negative numbers so 360 is added. Therefore, the negative of acos(y/arm) is
                # calculated as:   # 360 - acos(y/arm).
                #
                # There may be areas where a scan crosses over the edge of where it can reach using the
                # acos or must use its negative. In order to avoid swinging way around between scan points
                # when it doesn't have to, it first tries using the same type of angle (acos or its
                # negative) that it did last time in order to avoid unnecessary swings.
                past_reach = False
                if not used_negative_last_time:
                        try:
                                theta = degrees( acos( float(-y)/float(arm_length) ))
                        except ValueError:
                                past_reach = True
                else:
                        try:
                                theta = 360 - degrees( acos( float(-y)/float(arm_length) ))
                        except ValueError:
                                past_reach = True
                
                # If the acos call raised an exception, the desired y-value is beyond the reach
                # of the swing arm. Set the rotary axis straight up or down to do the best you can        
                if past_reach:
                        if( y > 0 ):
                                theta = 180.0
                        else:
                                theta = 0.0
                        if verbosity: print "Incapable of reaching location (%f, %f). Setting theta=%f" % (x, y, theta)

                X = x + arm_length * sin( radians( theta ) )

                # If the calculated X is out of bounds, swing theta to its negative (which could be back
                # to the natural acos)
                if X < min_X or X > max_X:
                        used_negative_last_time = not used_negative_last_time
                        theta = 360 - theta     
                        X = x - arm_length * sin( radians( theta ) )

                # If X is still out of bounds, it must be unachievable. Raise exception
                if X < min_X or X > max_X:
                        print "Unable to translate (%f, %f) to X-theta coordinates." % (x,y)
                        print "Calculated X value of %f is out of range." % X
                        raise SyntaxError
                
                # Put x-theta coord in scan list
                xtz = { 'x': X, 'theta': theta }
                if xyz.has_key('z0'):
                        xyz['z0'] = xyz['z0']
                if xyz.has_key('z1'):
                        xtz['z1'] = xyz['z1']   
                if xyz.has_key('t'):
                        xtz['t'] = xyz['t']
                if xyz.has_key('point-id'):
                        xtz['point-id'] = xyz['point-id']
                xthetaz_scan.append( xtz )
                if verbosity: print "Converted to", xtz, "from", xyz 

        return xthetaz_scan




def build_xyz_scan_from_target_corners( corners, target_width = 19.1, target_height = 26.8,
                                        num_h_scan_points = 4, num_v_scan_points = 5, just_corners = False, verbosity = 0):
        '''build_xyz_scan_from_target_corners( corners, well_width, well_height, num_h_scan_points, num_v_scan_points )

        Builds an xyz scan of points across a list of equally sized rectangular targets.

        The scan begins in the top-left corner of the first target and scans across and down it
        in an ess pattern that goes to the right across a row and left back across the next row.
        It then jumps to the top-left corner of the next target and scans it. Repeating until
        all of the targets are complete.

        It has no knowledge of the camera's field of view so the user must designate the correct
        number of horizontal and vertical scan points to achieve the correct step-over distances.

        The scan points alternate between starting with the given z0 and z1 in order to avoid
        the extra z-axis move back to z0 for each point.

        t values are constant for each target and assigned to all scan points
        '''
        cell_width = target_width/float(num_h_scan_points)
        cell_height = target_height/float(num_v_scan_points)

        # Iterate across rows and down columns to scan each target
        xyz_scan = []
        first_z_last_time = ''
        corner_num = 0
        for corner in corners:
                corner_num += 1
                # The center of the first cell isn't the corner, it's half a cell over (and down)
                x0 = corner['x'] - cell_width/2.0
                y0 = corner['y'] - cell_height/2.0
                for jj in range(num_v_scan_points):
                        for ii in range(num_h_scan_points):
                                xyz = {}
                                
                                # It is useful for location calibration to be able to find the corners of the
                                # wells. So with a True just_corners value we adjust the algorithm to skip all
                                # locations except the corners.
                                if not just_corners:
                                        i = ii
                                        j = jj
                                else:
                                        i = ii*(num_h_scan_points-1)
                                        j = jj*(num_v_scan_points-1)
                                        if ii > 1 or jj > 1:
                                                break

                                # Count even rows up and odd rows down to skip track back to 0
                                if j%2 == 0:
                                        xyz['x'] = x0 - i*cell_width
                                if j%2 == 1:
                                        xyz['x'] = x0 - (num_h_scan_points-1-i)*cell_width

                                xyz['y'] = y0 - j*cell_height

                                # If there is a second z-axis value, alternate which one you
                                # start with to avoid waiting for z to get back to z0 every time
                                if corner.has_key('z1'):
                                        if first_z_last_time != 'z0':
                                                xyz['z0'] = corner['z0']
                                                xyz['z1'] = corner['z1']
                                                first_z_last_time = 'z0'
                                        else:
                                                xyz['z0'] = corner['z1']
                                                xyz['z1'] = corner['z0']
                                                first_z_last_time = 'z1'
                                # If there's no second z value, just use the one you have
                                else:
                                        if xyz.has_key('z0'):
                                                xyz['z0'] = corner['z0']
                                                
                                if corner.has_key('t'):
                                        xyz['t'] = corner['t']

                                # Add cell identifier
                                xyz['point-id'] = "%d-%d-%d" % ( corner_num, j+1, i+1)
                                
                                # We're done with that point, add it to the new scan
                                xyz_scan.append( xyz )
                                if verbosity: print "Appended", xyz

        return xyz_scan




def generate_six_well_xy_corners( top_left_corner ):
        '''generate_six_well_xy_corners( top_left_corner_of_top_left_well )

        Takes the top-left corner of the top-left well and generates a list
        of the top-left corners of all six wells.

        The x-y values in this list can be used (with z and t values added)
        to generate a set of corners that generate a full scan
        with build_xyz_scan_from_target_corners()

        Takes a dictionary with two keys: 'x' and 'y'
        '''

        # These were calculated from the list of twelve well corners measured from the SolidWorks model
        delta_corners = [       {'y': 0.0, 'x': 0.0},
                                {'y': 38.3, 'x': 0.0},
                                {'y': 76.6, 'x': 0.0},
                                {'y': 8.7, 'x': 28.1},
                                {'y': 47.0, 'x': 28.1},
                                {'y': 85.3, 'x': 28.1}    ]

        corners = []
        for delta_corner in delta_corners:
                corner = {'x': (top_left_corner['x']-delta_corner['x']), 'y': (top_left_corner['y']-delta_corner['y']) }
                corners.append( corner )

        return corners
                                                                               
                


# Temporary x--theta scan for testing
xtz_keys = ( 'x', 'theta', 'z', 't' )
arb_test_xtz_scan = [ dict( zip(xtz_keys, ( 20, 45, 1, 0 ))) ]
arb_test_xtz_scan += [ dict( zip(xtz_keys, ( 40, 90, 4, 0 ))) ]
arb_test_xtz_scan += [ dict( zip(xtz_keys, ( 5, 120, 7, 0 ))) ]

xyz_keys = ( 'x', 'y', 'z0', 'z1', 't' )

# Place-holding xyz scan matrix for basic testing
# all numbers in mm
arb_test_xyz_scan = [ dict( zip(xyz_keys, ( 30, 50, 1, 4, 0 ))) ]
arb_test_xyz_scan += [ dict( zip(xyz_keys, ( 40, 40, 6, 0, 0 ))) ]
arb_test_xyz_scan += [ dict( zip(xyz_keys, ( 50, 30, 1, 4, 0 ))) ]
arb_test_xyz_scan += [ dict( zip(xyz_keys, ( 60, -20, 6, 0, 0 ))) ]
arb_test_xyz_scan += [ dict( zip(xyz_keys, ( 70, -10, 1, 4, 0 ))) ]
arb_test_xyz_scan += [ dict( zip(xyz_keys, ( 50, -10, 6, 0, 0 ))) ]



# First cut at flight-like scan
# Corners determined from solid model represent top and right edges of wells
corners_from_sw = ( {'x':152.2, 'y':47.3, 'z0':2.0, 'z1':4.0, 't':10},
            {'x':152.2, 'y':9.0, 'z0':0.0, 'z1':6.0, 't':3},
            {'x':152.2, 'y':-29.3, 'z0':1.5, 'z1':4.5, 't':3},
            {'x':124.1, 'y':47.3, 'z0':0.0, 'z1':6.0, 't':3},
            {'x':124.1, 'y':9.0, 'z0':2.0, 'z1':4.0, 't':3},
            {'x':124.1, 'y':-29.3, 'z0':0.0, 'z1':6.0, 't':3},
            {'x':28.1, 'y':47.3, 'z0':0.0, 't':3},
            {'x':28.1, 'y':9.0, 'z0':1.0, 't':3},
            {'x':28.1, 'y':-29.3, 'z0':2.0, 't':3},
            {'x':0.0, 'y':47.3, 'z0':3.0, 't':3},
            {'x':0.0, 'y':9.0, 'z0':4.0, 't':3},
            {'x':0.0, 'y':-29.3, 'z0':5.0, 't':3}
        )
model_xyz_scan = build_xyz_scan_from_target_corners( corners_from_sw )




# Heuristically found culture geometry on prototype
# generate scan from calculated corner
proto_home = {'x':69.0, 'y':56.0 }
proto_corners = generate_six_well_xy_corners( proto_home )
for corner in proto_corners:
        #corner['z0'] = 2.0
        #corner['z1'] = 5.0
        corner['t'] = 0.1
        #pass
proto_xyz_scan = build_xyz_scan_from_target_corners( proto_corners,
                                                     num_h_scan_points = 3,
                                                     num_v_scan_points = 4,
                                                     #just_corners = True,
                                                     verbosity = verbose_for_scan_build )
xyz_scan = proto_xyz_scan 
#xyz_scan = model_xyz_scan




if __name__ == '__main__':

        # Convert from xyz coordinates to x-theta-z coord
        try:
                xtz_scan = xyz_scan_2_xthetaz_scan( xyz_scan, verbosity = verbose_for_coord_trans )
        except SyntaxError:
                print "Unable to translate xyz scan points to x-theta-z. Exiting."
                sys.exit(0)


        # parse arguments
        # scancam [OPTION]... [SCANFILE]...
        #
        # -p, --min-period in minutes



        # open file and unpickle the scan

        # scan is a list of scanpoints represented as dictionaries with the keys:
        #	x	x-axis target location in mm
        #	theta	rotarty stage target location in deg
        #	z	z-axis target location in mm
        #	t	time in seconds to record video



        # Create serial connection
        # TODO: handle exceptions
        #ser = serial_connection('/dev/ttyS1')
        ser = serial_connection(comm_device)

        # TODO Flush serial port and anything else necessary to have clean comm start


        # Instantiate the axes
        # From T-LSM200A specs: mm_per_rev = .047625 um/microstep * 64 microstep/step * 200 steps/rev * .001 mm/um = .6096 mm/rev
        x_stage = linear_slide(ser, 1, mm_per_rev = .6096, verbose = verbose, run_mode = STEP)

        # From T-RS60A specs: .000234375 deg/microstep * 64 microsteps/step = .015 deg/step
        theta_stage = rotary_stage(ser, 2, deg_per_step = .015, verbose = verbose, run_mode = STEP)

        # From LSA10A-T4 specs: mm_per_rev = .3048 mm/rev
#        z_stage = linear_slide(ser, 3, mm_per_rev = .3048, verbose = verbose, run_mode = STEP)



        try:
                # Open serial connection
                print "Opening serial connection in thread"
                thread.start_new_thread( ser.open, ())


                # TODO: Send command to reset stages to defaults
                # TODO: Read in the default target speed for z so we can use it for z0 moves

                
                # Home all axes
                if home_on_start:
                        x_stage.home()
                        theta_stage.home()
                        z_stage.home()
                        x_stage.step()
                        theta_stage.step()
                        z_stage.step()
                        wait_for_actions_to_complete( (x_stage, theta_stage, z_stage), DEFAULT_STAGE_ACTION_TIMEOUT )

                        
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
                        print "Starting scan number", completed_scans + 1
                        scan_point_num = 0
                        for point in xtz_scan:

                                scan_point_num += 1
                                if verbose: print "Step", scan_point_num, point

                                # Enqueue scan point move commands
                                x_stage.move_absolute( point['x'] )
                                theta_stage.move_absolute( point['theta'] )
                                if point.has_key('z0'):
                                        z_stage.move_absolute( point['z0'] )
         
                                        # Set z-axis speed to moderately fast value. It may have been set to a different
                                        # value during an image-through-depth sequence
                                        z_stage.set_target_speed_in_units( STANDARD_Z_SPEED, 'A-series' )
                                        z_stage.step()

                                # Step to next queued scan point for all axes
                                x_stage.step()
                                theta_stage.step()
                                wait_for_actions_to_complete( (x_stage, theta_stage), DEFAULT_STAGE_ACTION_TIMEOUT )
#                                wait_for_actions_to_complete( (x_stage, theta_stage, z_stage), DEFAULT_STAGE_ACTION_TIMEOUT )

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
                                                        print target_z_speed, "is to fast. Setting to max speed:", MAX_Z_MOVE_SPEED, \
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
                                wait_for_actions_to_complete( (z_stage,), DEFAULT_STAGE_ACTION_TIMEOUT )

                        completed_scans += 1

                        if( just_one_scan == True ):
                                break
                        
        except KeyboardInterrupt:
                print "Completed", completed_scans, "scans."


        finally:            
                # Close serial connection before final exit
                print "Closing serial connection"
                ser.close()
                print "Connection closed"

