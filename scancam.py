import argparse, sys
from serial_connection import *
from linear_slides import *
from rotary_stages import *
from time import sleep, time
import thread
import pickle
from math import *



#
#
#
#
#
#
#
#
#
#
#
#




MAX_STAGE_ACTION_TIMEOUT = 100                # in seconds
DEFAULT_STAGE_ACTION_TIMEOUT = 50             # in seconds

min_period_bt_scans = 1                 # in minutes

verbose = True
home_on_start = False





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

                
# Convert xyz scan to x-theta-z
def xyz2xtz ( xyz_scan, arm_length = 55.0, min_X = 0.0, max_X = 176.0 ):
        '''
        xyz2xtz ( xyz_scan, arm_length, min_X, max_X )

        Use physical geometry to translate from a cartesian xyz coord to the one
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
                if not used_negative_last_time:
                        theta = degrees( acos( float(y)/float(arm_length) ))
                else:
                        theta = 360 - degrees( acos( float(y)/float(arm_length) ))

                X = x - arm_length * sin( radians( theta ) )

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
                xtz = { 'x': X, 'theta': theta, 'z0': xyz['z0'] }
                if xyz.has_key('z1'):
                        xtz['z1'] = xyz['z1']   
                if xyz.has_key('t'):
                        xtz['t'] = xyz['t']
                xthetaz_scan.append( xtz )
                if verbose: print "Converted to", xtz, "from", xyz 

        return xthetaz_scan




def build_xyz_scan_from_target_corners( corners, target_width = 19.1, target_height = 26.8,
                                        num_h_scan_points = 4, num_v_scan_points = 5):
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
        for corner in corners:
                # The center of the first cell isn't the corner, it's half a cell over (and down)
                x0 = corner['x'] + cell_width/2.0
                y0 = corner['y'] - cell_height/2.0
                for j in range(num_v_scan_points):
                        for i in range(num_h_scan_points):
                                xyz = {}
                                
                                # Count even rows up and odd rows down to skip track back to 0
                                if j%2 == 0:
                                        xyz['x'] = x0 + i*cell_width
                                if j%2 == 1:
                                        xyz['x'] = x0 + (num_h_scan_points-i)*cell_width

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
                                        xyz['z0'] = corner['z0']
                                                
                                if corner.has_key('t'):
                                        xyz['t'] = corner['t']

                                # We're done with that point, add it to the new scan
                                xyz_scan.append( xyz )
                                if verbose: print "Appended", xyz

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
                                {'y': 0.0, 'x': 28.1},
                                {'y': 38.3, 'x': 28.1},
                                {'y': 76.6, 'x': 28.1}    ]

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




if __name__ == '__main__':

        # Convert from xyz coordinates to x-theta-z coord
        try:
                model_xtz_scan = xyz2xtz( model_xyz_scan )
        except SyntaxError:
                print "Unable to translate xyz scan points to x-theta-z. Exiting."
                sys.exit(0)



        # Create serial connection
        # TODO: handle exceptions
        ser = serial_connection('COM1')



        # Instantiate the axes
        # From T-LSM200A specs: mm_per_rev = .047625 um/microstep * 64 microstep/step * 200 steps/rev * .001 mm/um = .6096 mm/rev
        x_stage = linear_slide(ser, 1, mm_per_rev = .6096, verbose = verbose, run_mode = STEP)

        # From T-RS60A specs: .000234375 deg/microstep * 64 microsteps/step = .015 deg/step
        theta_stage = rotary_stage(ser, 2, deg_per_step = .015, verbose = verbose, run_mode = STEP)

        # From LSA10A-T4 specs: mm_per_rev = .3048 mm/rev
        z_stage = linear_slide(ser, 3, mm_per_rev = .3048, verbose = verbose, run_mode = STEP)



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
                        scan_point = 0
                        for point in model_xtz_scan:

                                scan_point += 1
                                if verbose: print "Step", scan_point

                                # Enqueue scan point move commands
                                x_stage.move_absolute( point['x'] )
                                theta_stage.move_absolute( point['theta'] )
                                z_stage.move_absolute( point['z0'] )
         
                                # TODO: Set z-axis speed to default value. It may have been set to a different
                                # value during an image-through-depth sequence
                                z_stage.set_target_speed_in_units( 2.0, 'A-series' )

                                # Step to next queued scan point for all axes
                                x_stage.step()
                                theta_stage.step()
                                z_stage.step()
                                wait_for_actions_to_complete( (x_stage, theta_stage, z_stage), DEFAULT_STAGE_ACTION_TIMEOUT )

                                # Build video file target basename in the format:
                                #       <payload>_<scan definition ID>_<scan point>.<YYYY-MM-DD_HH-mm-SS>.h264

                                # If there is a second z-axis value, start the move to it as we start the video clip
                                # The clip will progress through the depth of the move
                                if point.has_key('z1'):
                                        # The move from z0 to z1 should take the same amount of time as the video clip duration
                                        target_speed = abs(point['z1']-point['z0']) / float(point['t'])
                                        z_stage.set_target_speed_in_units( target_speed, 'A-series' )
                        
                                        z_stage.move_absolute( point['z1'] )
                                        z_stage.step()                
                                
                                # Start raw video recording
                                if verbose: print "sleeping to simulate video capture"
                                sleep(1)

                                # Create video clip from raw frames
                                if verbose: print "sleep again to simulate video compression"
                                sleep(1)

                                # Assure that the last z-axis move was completed
                                wait_for_actions_to_complete( (z_stage,), DEFAULT_STAGE_ACTION_TIMEOUT )
                                
                        completed_scans += 1
                        
        except KeyboardInterrupt:
                print "Completed", completed_scans, "scans."


        finally:            
                # Close serial connection before final exit
                print "Closing serial connection"
                ser.close()
                print "Connection closed"

