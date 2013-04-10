import pickle
import scancam


# Heuristically found culture geometry on prototype
# generate scan from calculated corner
proto_centers = scancam.six_well_biocell_scan( {'x':69.0, 'y':29.2 },
                          scan_id = 'proto_centers2',
                          num_h_scan_points = 1,
                          num_v_scan_points = 1,
                          video_format_params = { 'subsampling': 3,
                                           'cropping': (320, 2240, 0, 1920) },
                          verbose = True )

proto_corners = scancam.six_well_biocell_just_corners_scan( {'x':69.0, 'y':29.2 },
                          scan_id = 'proto_corners2',
                          num_h_scan_points = 3,
                          num_v_scan_points = 4,
                          video_format_params = { 'subsampling': 3,
                                           'cropping': (320, 2240, 0, 1920) },
                          verbose = True )

scanfile = open("proto2.scan", 'wb')

pickle.dump( [proto_centers, proto_corners], scanfile)

scanfile.close()
