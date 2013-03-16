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

verbose = False

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
                #print "Device(s) still in action, sleep a sec"
                sleep(1)
                counter += 1
                if counter > timeout_secs:
                        print "Wait for actions to complete: timeout after %d secs" % counter
                        break

                
# Convert xyz scan to x-theta-z
def xyz2xtz ( xyz_scan, arm_length = 55.0, min_X = 0.0, max_X = 176.0 ):

        xthetaz_scan = []
        xt_keys = ( 'x', 'theta', 'z' )
        used_negative_last_time = False
        for xyz in xyz_scan:
                x = xyz['x']
                y = xyz['y']

                # Calculate Radial Coordinates
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

                # Put x-theta coord in scan list
                xtz = dict( zip( xt_keys, ( X, theta, xyz['z'])))
                xthetaz_scan.append( xtz )
                if verbose: print "Converted to", xt, "from", xy 

        return xthetaz_scan

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

# Temporary x--theta scan for testing
xtz_keys = ( 'x', 'theta', 'z', 't' )
arb_test_xtz_scan = [ dict( zip(xtz_keys, ( 20, 45, 1, 0 ))) ]
arb_test_xtz_scan += [ dict( zip(xtz_keys, ( 40, 90, 4, 0 ))) ]
arb_test_xtz_scan += [ dict( zip(xtz_keys, ( 5, 120, 7, 0 ))) ]

xyz_keys = ( 'x', 'y', 'z', 't' )

# Place-holding xyz scan matrix for basic testing
# all numbers in mm
arb_test_xyz_scan = [ dict( zip(xyz_keys, ( 30, 50, 5, 0 ))) ]
arb_test_xyz_scan += [ dict( zip(xyz_keys, ( 40, 40, 5, 0 ))) ]
arb_test_xyz_scan += [ dict( zip(xyz_keys, ( 50, 30, 5, 0 ))) ]
arb_test_xyz_scan += [ dict( zip(xyz_keys, ( 60, -20, 5, 0 ))) ]
arb_test_xyz_scan += [ dict( zip(xyz_keys, ( 70, -10, 5, 0 ))) ]
arb_test_xyz_scan += [ dict( zip(xyz_keys, ( 50, -10, 5, 0 ))) ]



# First cut at flight-like scan

# Constants used for calculating xyz scan matrix 
well_width = 19.1
well_height = 26.8
h_scan_points = 4
v_scan_points = 5
fov_width = well_width/float(h_scan_points)
fov_height = well_height/float(v_scan_points)

default_z = 3.0
# Corners determined from solid model represent top and right edges of wells
corners = ( {'x':152.2, 'y':47.3, 'z':5.0},
            {'x':152.2, 'y':9.0, 'z':1.0},
            {'x':152.2, 'y':-29.3, 'z':2.0},
            {'x':124.1, 'y':47.3, 'z':3.0},
            {'x':124.1, 'y':9.0, 'z':4.0},
            {'x':124.1, 'y':-29.3, 'z':5.0},
            {'x':28.1, 'y':47.3, 'z':0.0},
            {'x':28.1, 'y':9.0, 'z':1.0},
            {'x':28.1, 'y':-29.3, 'z':2.0},
            {'x':0.0, 'y':47.3, 'z':3.0},
            {'x':0.0, 'y':9.0, 'z':4.0},
            {'x':0.0, 'y':-29.3, 'z':5.0}
        )

# Iterate 4 columns across and 5 rows down across each well from corner
model_xyz_scan = []
for corner in corners:
        x0 = corner['x'] + fov_width/2.0
        y0 = corner['y'] - fov_height/2.0
        for j in range(v_scan_points):
                for i in range(h_scan_points):
                        # Count even rows up and odd rows down to skip track back to 0
                        if j%2 == 0: model_xyz_scan.append( { 'x':x0+i*fov_width, 'y':y0-j*fov_height, 'z':corner['z'] } )
                        if j%2 == 1: model_xyz_scan.append( { 'x':x0+(h_scan_points-i)*fov_width, 'y':y0-j*fov_height, 'z':corner['z'] } )
                                        

# Convert from xyz coordinates to x-theta-z coord
model_xtz_scan = xyz2xtz( model_xyz_scan )


#sys.exit(0)

# Create serial connection
# TODO: handle exceptions
ser = serial_connection('COM1')


try:
        # Instantiate the axes
        # From T-LSM200A specs: mm_per_rev = .047625 um/microstep * 64 microstep/step * 200 steps/rev * .001 mm/um = .61 mm/rev
        x_stage = linear_slide(ser, 1, mm_per_rev = .61, verbose = verbose, run_mode = STEP)

        # From T-RS60A specs: .000234375 deg/microstep * 64 microsteps/step = .015 deg/step
        theta_stage = rotary_stage(ser, 2, deg_per_step = .015, verbose = verbose, run_mode = STEP)

        # From LSA10A-T4 specs: mm_per_rev = .3048 mm/rev
        z_stage = linear_slide(ser, 3, mm_per_rev = .3048, verbose = verbose, run_mode = STEP)
        
        # Open serial connection
        print "Opening serial connection in thread"
        thread.start_new_thread( ser.open, ())

        # Home all axes
        x_stage.home()
        theta_stage.home()
        z_stage.home()
        x_stage.step()
        theta_stage.step()
        z_stage.step()
        wait_for_actions_to_complete( (x_stage, theta_stage), DEFAULT_STAGE_ACTION_TIMEOUT )

                
        # Loop and continually start scans with a timed periodicity
        completed_scans = 0
        last_scan_start_time = 0
        while (1):

                # Once a second, check to see if it's time to start a new scan
                if time() <= last_scan_start_time + min_period_bt_scans*60.0:
                        sleep(1)
                        continue
                last_scan_start_time = time()
                
                # Enqueue scan point move commands
                for point in model_xtz_scan:
                        x_stage.move_absolute( point['x'] )
                        theta_stage.move_absolute( point['theta'] )
                        z_stage.move_absolute( point['z'] )
                        
                # Step through scan
                print "Starting scan number", completed_scans + 1
                scan_point = 0
                while         len(x_stage.command_queue) > 0 and \
                              len(theta_stage.command_queue) > 0 and \
                              len(z_stage.command_queue) > 0:
                        
                        # Step to next queued scan point for all axes
                        x_stage.step()
                        theta_stage.step()
                        z_stage.step()
                        scan_point += 1
                        if verbose: print "Step", step_num
                        wait_for_actions_to_complete( (x_stage, theta_stage, z_stage), DEFAULT_STAGE_ACTION_TIMEOUT )

                        # Build video file target basename in the format:
                        #       <payload>_<scan definition ID>_<scan point>.<YYYY-MM-DD_HH-mm-SS>.h264
                                               
                        # Start raw video recording
                        if verbose: print "sleeping to simulate video capture"
                        sleep(1)

                        # Create video clip from raw frames
                        if verbose: print "sleep again to simulate video compression"
                        sleep(1)

                completed_scans += 1
                
        # Home all axes
        x_stage.home()
        theta_stage.home()
        z_stage.home()
        x_stage.step()
        theta_stage.step()
        z_stage.step()
        wait_for_actions_to_complete( (x_stage, theta_stage, z_stage), DEFAULT_STAGE_ACTION_TIMEOUT )

except KeyboardInterrupt:
        print "Completed", completed_scans, "scans."


finally:            
        # Close serial connection before final exit
        print "Closing serial connection"
        ser.close()
        print "Connection closed"

