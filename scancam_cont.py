import argparse
from serial_connection import *
from linear_slides import *
from rotary_stages import *
from time import sleep
import thread

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

keys = ( 'x', 'theta', 'z', 't' )
scanpoints = [ dict( zip(keys, ( 20, 45, 1, 0 ))) ]
scanpoints += [ dict( zip(keys, ( 40, 90, 4, 0 ))) ]
#scanpoints += [ dict( zip(keys, ( 5, 120, 7, 0 ))) ]


# create serial connection
#try:
ser = serial_connection('COM1')
#except SerialException:
#        print "Serial Exception"
#        raise

try:

        # instantiate the axes
        x = linear_slide(ser, 1, mm_per_rev = .61, verbose = True, run_mode = CONTINUOUS)
        theta = rotary_stage(ser, 2, deg_per_step = .015, verbose = True, run_mode = CONTINUOUS)

        print "pending responses for x:", x.pending_responses, " and theta:", theta.pending_responses

        #print "Opening serial connection"
        #thread.start_new_thread( ser.open, ())

        # load scan point move commands
        for point in scanpoints:
                x.move_absolute( point['x'] )
                theta.move_absolute( point['theta'] )

                counter = 0
                while x.responses_pending() or theta.responses_pending():
                        counter += 1
                        #print "Last move(s) not complete, sleep a sec", x.in_action(), theta.in_action()
                        print "Waiting to hear back from device(s), sleep a sec", x.pending_responses, theta.pending_responses
                        sleep(1)
                        if counter > 15:
                                print "Timeout"
                                break
                
                print "Move finished or timed out: Sleeping to simulate video capture", x.pending_responses, theta.pending_responses
                sleep(5)
                print "sleep again to simulate video compression", x.pending_responses, theta.pending_responses
                sleep(5)
                
        x.home()
        theta.home()

        sleep(20)

        print "pending responses for x:", x.pending_responses, " and theta:", theta.pending_responses

finally:            
        print "Closing serial connection"
        ser.close()
        print "Connection closed"

