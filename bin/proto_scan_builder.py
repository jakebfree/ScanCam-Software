import pickle
import scancam


# Heuristically found culture geometry on prototype
# generate scan from calculated corner
proto = scancam.SixWellBioCellScan( {'x':69.0, 'y':29.2 },
                          scan_id = 'proto',
                          num_h_scan_points = 3,
                          num_v_scan_points = 4,
                          clip_duration = 15,
                          video_format_params = { 'subsampling': 3,
                                           'cropping': (320, 2240, 0, 1920) },
                          verbose = True )

scanfile = open("proto.scan", 'wb')
pickle.dump( [proto], scanfile)
scanfile.close()


proto_corners = scancam.SixWellBioCellJustCornersScan( {'x':69.0, 'y':29.2 },
                          scan_id = 'proto2',
                          num_h_scan_points = 3,
                          num_v_scan_points = 4,
                          clip_duration = 5,
                          video_format_params = { 'subsampling': 3,
                                           'cropping': (320, 2240, 0, 1920) },
                          verbose = True )

scanfile = open("proto_corners.scan", 'wb')
pickle.dump( [proto_corners], scanfile)
scanfile.close()


proto_centers = scancam.SixWellBioCellScan( {'x':69.0, 'y':29.2 },
                          scan_id = 'proto2',
                          num_h_scan_points = 1,
                          num_v_scan_points = 1,
                          clip_duration = 5,
                          video_format_params = { 'subsampling': 3,
                                           'cropping': (320, 2240, 0, 1920) },
                          verbose = True )

scanfile = open("proto_centers.scan", 'wb')
pickle.dump( [proto_centers], scanfile)
scanfile.close()
