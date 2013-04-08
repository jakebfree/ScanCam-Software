import thread
from time import sleep
import argparse
import sys

from serial_connection import *
from linear_slides import *
from rotary_stages import *
from scancam import *

import logging, idscam.common.syslogger

log = idscam.common.syslogger.get_syslogger('scancam_tester', level=logging.DEBUG)

log.warning("warning log")
log.info("info log")
log.critical("critical log")
log.debug("debug log")

WAIT_TIME = 100


parser = argparse.ArgumentParser(fromfile_prefix_chars='@')
parser.add_argument('-p', '--period', type=float, default=0.0, help="Minimum number of minutes between the start of scans. If the scan itself takes longer than the period, they will run back-to-back")
parser.add_argument('-l', '--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'CRITICAL'], default='INFO', help="Level of logging")
looping_group = parser.add_mutually_exclusive_group()
looping_group.add_argument('-n', '--num-scans', type=int, default=1, help="Number of scans to perform before exiting")
looping_group.add_argument('-c', '--continuous', action="store_true", help="Take scans continually without exiting")
parser.add_argument('--home-on-start', action='store_true', default=True, help="Home all stages on startup. Only set to false during development testing to avoid long waits for home and back")

configs = parser.add_argument_group('configs', "Arguments generally read from scancam.conf file. May be overridden at command line")
configs.add_argument('-s', '--serial-dev', default='/dev/ttyUSB0', help="Serial device identifier. Linux example: '/dev/ttyUSB0', Windows example: 'COM1'")
configs.add_argument('--stage-timeout', type=int, default=100, help="Number of seconds for stages to try on move before timing out")
configs.add_argument('--camera-warmup', type=float, default=0.0, help="Time in seconds (float) between camera system call and beginning of clip. Used to adjust speed of video-through-depth z-axis move") 

print sys.argv

args = parser.parse_args(['@scancam.conf'] + sys.argv[1:])
argd = vars(parser.parse_args(['@scancam.conf'] + sys.argv[1:]))

print "argd:", argd

print args.period
print args.log_level
print args.num_scans
print args.continuous
print args.serial_dev
print args.stage_timeout
print args.camera_warmup
print args.home_on_start

sys.exit(0)

ser = serial_connection('/dev/ttyUSB0')


try:
    # for x_stage (T-LSM200A)
    x_stage = linear_slide(ser, 1, mm_per_rev = .6096, verbose = True, run_mode = STEP)

    # for theta rotary stage (
    theta_stage = rotary_stage(ser, 2, deg_per_step = .015, verbose = True, run_mode = STEP)

    # for z_stage    (LSA10A-T4) 
    #z_stage = linear_slide(ser, 3, mm_per_rev = .3048, verbose = True, run_mode = STEP)

    # Start thread for serial commnunication
    thread.start_new_thread( ser.open, ())

    camera = ueye_camera(cam_device_id = 1, verbose = True) 

    scancam = xthetaz_scancam( [x_stage, theta_stage], camera )

    scancam.home()

    scancam.move({'x':75, 'y':30}, False)

    scancam.wait_for_stages_to_complete_actions(100)

    print "Done with move"
    
except KeyboardInterrupt:
    scancam.stop()
        

finally:            
    # Close serial connection before final exit
    print "Closing serial connection"
    ser.close()
    print "Connection closed"









