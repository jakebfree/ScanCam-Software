import thread
from time import sleep
import argparse
import sys

from serial_connection import *
from linear_slides import *
from rotary_stages import *
from scancam import *

import logging, idscam.common.syslogger



# Parse command line arguments
parser = argparse.ArgumentParser(fromfile_prefix_chars='@')
parser.add_argument('-l', '--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'CRITICAL'], default='DEBUG', help="Level of logging")
parser.add_argument('--home-on-start', action='store_true', default=True, help="Home all stages on startup. Only set to false during development testing to avoid long waits for home and back")
parser.add_argument('-s', '--serial-dev', default='/dev/ttyUSB0', help="Serial device identifier. Linux example: '/dev/ttyUSB0', Windows example: 'COM1'")
parser.add_argument('--stage-timeout', type=int, default=100, help="Number of seconds for stages to try on move before timing out")

print "log level:", str(args.log_level)

log = idscam.common.syslogger.get_syslogger('scancam_tester')
# Set up logging
if args.log_level == 'DEBUG':
        log.setLevel(logging.DEBUG)
elif args.log_level == 'INFO':
        log.setLevel(logging.INFO)
elif args.log_level == 'WARNING':
        log.setLevel(logging.WARNING)
elif args.log_level == 'CRITICAL':
        log.setLevel(logging.CRITICAL)
else:
        print "Logging level not available. Exiting."
        sys.exit(1)

log.critical("Logging critical messages.")
log.warning("Logging warning messages.")
log.info("Logging info messages")
log.debug("Logging debug messages")

# Log all variables handled by config file and command line args
log.info("Variables handled by config file and command line args:")
arg_dict = vars(args)
for arg in arg_dict:
        log.info("    " + arg + ": " + str(arg_dict[arg]))

sys.exit(0)

ser = serial_connection(args.serial_dev)


try:
    # for x_stage (T-LSM200A)
    x_stage = linear_slide(ser, 1, mm_per_rev = .6096, verbose = True, run_mode = STEP)

    # for theta rotary stage (
    theta_stage = rotary_stage(ser, 2, deg_per_step = .015, verbose = True, run_mode = STEP)

    # for z_stage    (LSA10A-T4) 
    #z_stage = linear_slide(ser, 3, mm_per_rev = .3048, verbose = True, run_mode = STEP)

    # Start thread for serial commnunication
    thread.start_new_thread( ser.open, ())

    camera = ueye_camera(cam_device_id = 1, log_level = log.getEffectiveLevel() ) 

    print "status:", camera.daemon_call('status')
    print "start:", camera.daemon_call('start')
    camera.restart_daemon()

    scancam = xthetaz_scancam( [x_stage, theta_stage], camera )

    if args.home_on_start:
        scancam.home()
                                                        
    scancam.move({'x':75, 'y':30}, False)

    scancam.wait_for_stages_to_complete_actions(args.stage_timeout)

    print "Done with move"
    
except KeyboardInterrupt:
    scancam.stop()
        

finally:            
    # Close serial connection before final exit
    print "Closing serial connection"
    ser.close()
    print "Connection closed"









