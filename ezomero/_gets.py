import logging
import os
import numpy as np
from typing import Optional, List, Union, Tuple, Literal
from typing import Any
from ._ezomero import do_across_groups
from omero.gateway import FileAnnotationWrapper, BlitzGateway, ImageWrapper
from omero import ApiUsageException, InternalException
from omero.model import MapAnnotationI, TagAnnotationI, Shape
from omero.model import CommentAnnotationI
from omero.grid import Table
from omero.rtypes import rint, rlong
from omero.sys import Parameters
from omero.model import enums as omero_enums
from .rois import Point, Line, Rectangle
from .rois import Ellipse, Polygon, Polyline, Label, ezShape
import importlib.util

if (importlib.util.find_spec('pandas')):
    import pandas as pd
    has_pandas = True
else:
    has_pandas = False


# gets
@do_across_groups
def get_image(conn: BlitzGateway, image_id: int,
              no_pixels: Optional[bool] = False,
              start_coords: Optional[Union[List[int], Tuple[int, ...]]] = None,
              axis_lengths: Optional[Union[List[int], Tuple[int, ...]]] = None,
              xyzct: Optional[bool] = False,
              pad: Optional[bool] = False,
              pyramid_level: Optional[int] = None,
              dim_order: Optional[str] = None,
              across_groups: Optional[bool] = True
              ) -> Tuple[Union[ImageWrapper, None], Union[np.ndarray, None]]:
    """Get omero image object along with pixels as a numpy array.

    Parameters
    ----------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    image_id : int
        Id of the image to get.
    no_pixels : bool, optional
        If true, no pixel data is returned, only the OMERO image object.
        Default is `False`.
    start_coords : list or tuple of int, optional
        Starting coordinates for each axis for the pixel region to be returned
        if `no_pixels` is `False` (assumes XYZCT ordering). If `None`, the zero
        coordinate is used for each axis. Default is None.
    axis_lengths : list or tuple of int, optional
        Lengths for each axis for the pixel region to be returned if
        `no_pixels` is `False`. If `None`, the lengths will be set such that
        the entire possible range of pixels is returned. Default is None.
    xyzct : bool, optional
        Option to return array with dimensional ordering XYZCT. If `False`, the
        ``skimage`` preferred ordering will be used (TZYXC). Default is False.
    pad : bool, optional
        If `axis_lengths` values would result in out-of-bounds indices, pad
        pixel array with zeros. Otherwise, such an operation will raise an
        exception. Ignored if `no_pixels` is True.
    pyramid_level : int, optional
        If image has multiple pyramid levels and this argument is set, pixels
        are returned at the chosen resolution level, and all other arguments
        apply to that level as well. We follow the usual convention of `0` as
        full-resolution.
    dim_order : str, optional
        String containing the letters 'x', 'y', 'z', 'c' and 't' in some order,
        specifying the order of dimensions to be returned by the function.
        If specified, ignores the value of the 'xyzct' variable.
    across_groups : bool, optional
        Defines cross-group behavior of function - set to
        ``False`` to disable it.

    Returns
    -------
    image : ``omero.gateway.ImageWrapper`` object
        OMERO image object.
    pixels : ndarray
        Array containing pixel values from OMERO image. Can be a subregion
        of the image if `start_coords` and `axis_lengths` are specified.

    Notes
    -----
    Regardless of whether `xyzct` is `True` or `dim_order` is set, the numpy
    array is created as TZYXC, for performance reasons. If `xyzct` is `True`
    or `dim_order` is set, the returned `pixels` array is actually a view
    of the original TZYXC array.

    Examples
    --------
    # Get an entire image as a numpy array:

    >>> im_object, im_array = get_image(conn, 314)

    # Get a subregion of an image as a numpy array:

    >>> im_o, im_a = get_image(conn, 314, start_coords=(40, 50, 4, 0, 0),
    ...                        axis_lengths=(256, 256, 12, 10, 10))

    # Get only the OMERO image object, no pixels:

    >>> im_object, _ = get_image(conn, 314, no_pixels=True)
    >>> im_object.getId()
    314
    """

    if start_coords is not None:
        if type(start_coords) not in (list, tuple):
            raise TypeError('start_coords must be supplied as list or tuple')
        if len(start_coords) != 5:
            raise ValueError('start_coords must have length 5 (XYZCT)')

    if axis_lengths is not None:
        if type(axis_lengths) not in (list, tuple):
            raise TypeError('axis_lengths must be supplied as list of tuple')
        if len(axis_lengths) != 5:
            raise ValueError('axis_lengths must have length 5 (XYZCT)')

    if image_id is None:
        raise TypeError('Object ID cannot be empty')
    if type(image_id) is not int:
        raise TypeError('Image ID must be an integer')

    if pyramid_level is not None:
        if type(pyramid_level) is not int:
            raise TypeError('pyramid_level must be an int')

    if dim_order is not None:
        if type(dim_order) is not str:
            raise TypeError('dim_order must be a str')
        if set(dim_order.lower()) != set('xyzct'):
            raise ValueError('dim_order must contain letters '
                             'xyzct exactly once')

    pixel_view = None
    image = conn.getObject('Image', image_id)
    if image is None:
        logging.warning(f'Cannot load image {image_id} - '
                        'check if you have permissions to do so')
        return (None, None)
    size_x = image.getSizeX()
    size_y = image.getSizeY()
    size_z = image.getSizeZ()
    size_c = image.getSizeC()
    size_t = image.getSizeT()
    pixels_dtype = image.getPixelsType()
    orig_sizes = [size_x, size_y, size_z, size_c, size_t]

    if no_pixels is False:

        # check if we are getting full-res or pyramid level
        if pyramid_level is None or pyramid_level == 0:
            # full-res image - can use original sizes
            if start_coords is None:
                start_coords = (0, 0, 0, 0, 0)

            if axis_lengths is None:
                axis_lengths = (orig_sizes[0] - start_coords[0],  # X
                                orig_sizes[1] - start_coords[1],  # Y
                                orig_sizes[2] - start_coords[2],  # Z
                                orig_sizes[3] - start_coords[3],  # C
                                orig_sizes[4] - start_coords[4])  # T

            primary_pixels = image.getPrimaryPixels()
            reordered_sizes = [axis_lengths[4],
                               axis_lengths[2],
                               axis_lengths[1],
                               axis_lengths[0],
                               axis_lengths[3]]
            pixels = np.zeros(reordered_sizes, dtype=pixels_dtype)

            # get pixels

        # check here if you need to trim the axis_lengths, trim if necessary
            overhangs = [(al + sc) - osz
                         for al, sc, osz
                         in zip(axis_lengths,
                                start_coords,
                                orig_sizes)]
            overhangs = [np.max((0, o)) for o in overhangs]
            if any([x > 0 for x in overhangs]) & (pad is False):
                raise IndexError('Attempting to access out-of-bounds pixel. '
                                 'Either adjust axis_lengths or use pad=True')

            axis_lengths = [al - oh for al, oh in zip(axis_lengths, overhangs)]
            zct_tuples: List[Tuple[int, ...]] = []
            for z in range(start_coords[2],
                           start_coords[2] + axis_lengths[2]):
                for c in range(start_coords[3],
                               start_coords[3] + axis_lengths[3]):
                    for t in range(start_coords[4],
                                   start_coords[4] + axis_lengths[4]):
                        zct_tuples.append((z, c, t))
            zct_list = [list(zct) for zct in zct_tuples]

            if reordered_sizes == [size_t, size_z, size_y, size_x, size_c]:
                plane_gen = primary_pixels.getPlanes(zct_tuples)
            else:
                tile = (start_coords[0], start_coords[1],
                        axis_lengths[0], axis_lengths[1])
                zct_tiles: List[Tuple[int, int, int, Tuple[int, ...]]] = []
                for zct in zct_list:
                    zct_tiles.append((zct[0], zct[1], zct[2], tile))
                plane_gen = primary_pixels.getTiles(zct_tiles)

            for i, plane in enumerate(plane_gen):
                zct_coords = zct_list[i]
                z = zct_coords[0] - start_coords[2]
                c = zct_coords[1] - start_coords[3]
                t = zct_coords[2] - start_coords[4]
                pixels[t, z, :axis_lengths[1], :axis_lengths[0], c] = plane

            if dim_order is not None:
                order_dict = dict(zip(dim_order, range(5)))
                order_vector = [order_dict[c.lower()] for c in 'tzyxc']
                pixel_view = np.moveaxis(pixels,
                                         [0, 1, 2, 3, 4],
                                         order_vector)
            else:
                if xyzct is True:
                    pixel_view = np.moveaxis(pixels,
                                             [0, 1, 2, 3, 4],
                                             [4, 2, 1, 0, 3])
                else:
                    pixel_view = pixels

        else:
            # get specific pyramid level
            PIXEL_TYPES = {
                            omero_enums.PixelsTypeint8: np.int8,
                            omero_enums.PixelsTypeuint8: np.uint8,
                            omero_enums.PixelsTypeint16: np.int16,
                            omero_enums.PixelsTypeuint16: np.uint16,
                            omero_enums.PixelsTypeint32: np.int32,
                            omero_enums.PixelsTypeuint32: np.uint32,
                            omero_enums.PixelsTypefloat: np.float32,
                            omero_enums.PixelsTypedouble: np.float64,
                          }
            pix = image._conn.c.sf.createRawPixelsStore()
            pid = image.getPixelsId()
            pix.setPixelsId(pid, False)
            res_levels = [(r.sizeX, r.sizeY)
                          for r in pix.getResolutionDescriptions()]
            pix.setResolutionLevel((len(res_levels) - pyramid_level - 1))
            size_w, size_h = res_levels[pyramid_level]
            orig_sizes = [size_w, size_h, size_z, size_c, size_t]
            if start_coords is None:
                start_coords = (0, 0, 0, 0, 0)

            if axis_lengths is None:
                axis_lengths = (size_w - start_coords[0],  # X
                                size_h - start_coords[1],  # Y
                                orig_sizes[2] - start_coords[2],  # Z
                                orig_sizes[3] - start_coords[3],  # C
                                orig_sizes[4] - start_coords[4])  # T
            primary_pixels = image.getPrimaryPixels()
            reordered_sizes = [axis_lengths[4],
                               axis_lengths[2],
                               axis_lengths[1],
                               axis_lengths[0],
                               axis_lengths[3]]
            pixels = np.zeros(reordered_sizes, dtype=pixels_dtype)
    # check here if you need to trim the axis_lengths, trim if necessary
            overhangs = [(al + sc) - osz
                         for al, sc, osz
                         in zip(axis_lengths,
                                start_coords,
                                orig_sizes)]
            overhangs = [np.max((0, o)) for o in overhangs]
            if any([x > 0 for x in overhangs]) & (pad is False):
                raise IndexError('Attempting to access out-of-bounds pixel. '
                                 'Either adjust axis_lengths or use pad=True')
            axis_lengths = [al - oh for al, oh in zip(axis_lengths, overhangs)]
            # get pixels
            zct_list = []
            for z in range(start_coords[2],
                           start_coords[2] + axis_lengths[2]):
                for c in range(start_coords[3],
                               start_coords[3] + axis_lengths[3]):
                    for t in range(start_coords[4],
                                   start_coords[4] + axis_lengths[4]):
                        zct_list.append([z, c, t])

            dtype = PIXEL_TYPES.get(primary_pixels.getPixelsType().value, None)
            if reordered_sizes == [size_t, size_z, size_h, size_w, size_c]:
                # getting whole plane
                plane_gen = []
                for zct in zct_list:
                    byte_plane = pix.getPlane(*zct)
                    plane = np.frombuffer(byte_plane, dtype=dtype)
                    plane = plane.reshape((size_h, size_w))
                    plane_gen.append(plane)

            else:
                plane_gen = []
                tile = (start_coords[0], start_coords[1],
                        axis_lengths[0], axis_lengths[1])
                for zct in zct_list:
                    this_tile = pix.getTile(*zct, *tile)
                    this_tile = np.frombuffer(this_tile, dtype=dtype)
                    this_tile = this_tile.reshape((tile[3], tile[2]))
                    plane_gen.append(this_tile)

            for i, plane in enumerate(plane_gen):
                zct_coords = zct_list[i]
                z = zct_coords[0] - start_coords[2]
                c = zct_coords[1] - start_coords[3]
                t = zct_coords[2] - start_coords[4]
                pixels[t, z, :axis_lengths[1], :axis_lengths[0], c] = plane
            if dim_order is not None:
                order_dict = dict(zip(dim_order, range(5)))
                order_vector = [order_dict[c.lower()] for c in 'tzyxc']
                pixel_view = np.moveaxis(pixels,
                                         [0, 1, 2, 3, 4],
                                         order_vector)
            else:
                if xyzct is True:
                    pixel_view = np.moveaxis(pixels,
                                             [0, 1, 2, 3, 4],
                                             [4, 2, 1, 0, 3])
                else:
                    pixel_view = pixels
            pix.close()
    return (image, pixel_view)


@do_across_groups
def get_image_ids(conn: BlitzGateway, project: Optional[int] = None,
                  dataset: Optional[int] = None,
                  plate: Optional[int] = None,
                  well: Optional[int] = None,
                  plate_acquisition: Optional[int] = None,
                  annotation: Optional[int] = None,
                  across_groups: Optional[bool] = True) -> List[int]:
    """Return a list of image ids based on image container

    If no container is specified, function will return orphans.

    Parameters
    ----------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    project : int, optional
        ID of Project from which to return image IDs. This will return IDs of
        all images contained in all child Datasets of the specified Project.
    dataset : int, optional
        ID of Dataset from which to return image IDs.
    plate : int, optional
        ID of Plate from which to return image IDs. This will return IDs of
        all images contained in all Wells belonging to the specified Plate.
    well : int, optional
        ID of Well from which to return image IDs.
    plate_acquisition : int, optional
        ID of Plate acquisition from which to return image IDs.
    annotation : int, optional
        ID of Annotation from which to return image IDs. This will return IDs
        of all images linked to the specified annotation.
    across_groups : bool, optional
        Defines cross-group behavior of function - set to
        ``False`` to disable it.

    Returns
    -------
    im_ids : list of ints
        List of image IDs contained in the specified container.

    Notes
    -----
    User and group information comes from the `conn` object. Be sure to use
    ``ezomero.set_group`` to specify group prior to passing
    the `conn` object to this function.

    Only one of Project, Dataset, Plate, Well, Plate acquisition or Annotation
    can be specified. If none of those are specified, orphaned images are
    returned.

    Examples
    --------
    # Return orphaned images:

    >>> orphans = get_image_ids(conn)

    # Return IDs of all images from Dataset with ID 448:

    >>> ds_ims = get_image_ids(conn, dataset=448)

    # Return IDs of all images annotated with Tag ID 876:

    >>> tag_ims = get_image_ids(conn, annotation=876)
    """
    arg_counter = 0

    for arg in [project, dataset, plate, well, plate_acquisition, annotation]:
        if arg is not None:
            arg_counter += 1
    if arg_counter > 1:
        raise ValueError('Only one of Project/Dataset/Plate/Well'
                         '/PlateAcquisition/Annotation can be specified')

    q = conn.getQueryService()
    params = Parameters()

    if project is not None:
        if not isinstance(project, int):
            raise TypeError('Project ID must be integer')
        params.map = {"project": rlong(project)}
        results = q.projection(
            "SELECT i.id FROM Project p"
            " JOIN p.datasetLinks pdl"
            " JOIN pdl.child d"
            " JOIN d.imageLinks dil"
            " JOIN dil.child i"
            " WHERE p.id=:project",
            params,
            conn.SERVICE_OPTS
            )
    elif dataset is not None:
        if not isinstance(dataset, int):
            raise TypeError('Dataset ID must be integer')
        params.map = {"dataset": rlong(dataset)}
        results = q.projection(
            "SELECT i.id FROM Dataset d"
            " JOIN d.imageLinks dil"
            " JOIN dil.child i"
            " WHERE d.id=:dataset",
            params,
            conn.SERVICE_OPTS
            )
    elif plate is not None:
        if not isinstance(plate, int):
            raise TypeError('Plate ID must be integer')
        params.map = {"plate": rlong(plate)}
        results = q.projection(
            "SELECT i.id FROM Plate pl"
            " JOIN pl.wells w"
            " JOIN w.wellSamples ws"
            " JOIN ws.image i"
            " WHERE pl.id=:plate",
            params,
            conn.SERVICE_OPTS
            )
    elif well is not None:
        if not isinstance(well, int):
            raise TypeError('Well ID must be integer')
        params.map = {"well": rlong(well)}
        results = q.projection(
            "SELECT i.id FROM Well w"
            " JOIN w.wellSamples ws"
            " JOIN ws.image i"
            " WHERE w.id=:well",
            params,
            conn.SERVICE_OPTS
            )
    elif plate_acquisition is not None:
        if not isinstance(plate_acquisition, int):
            raise TypeError('Plate acquisition ID must be integer')
        params.map = {"plate_acquisition": rlong(plate_acquisition)}
        results = q.projection(
            "SELECT i.id FROM WellSample ws"
            " JOIN ws.image i"
            " JOIN ws.plateAcquisition pa"
            " WHERE pa.id=:plate_acquisition",
            params,
            conn.SERVICE_OPTS
            )
    elif annotation is not None:
        if not isinstance(annotation, int):
            raise TypeError('Annotation ID must be integer')
        params.map = {"annotation": rlong(annotation)}
        results = q.projection(
            "SELECT l.parent.id FROM ImageAnnotationLink l"
            " WHERE l.child.id=:annotation",
            params,
            conn.SERVICE_OPTS
            )
    else:
        results = q.projection(
            "SELECT i.id FROM Image i"
            " WHERE NOT EXISTS ("
            " SELECT dil FROM DatasetImageLink dil"
            " WHERE dil.child=i.id"
            " )"
            " AND NOT EXISTS ("
            " SELECT ws from WellSample ws"
            " WHERE ws.image=i.id"
            " )",
            params,
            conn.SERVICE_OPTS
            )

    return [r[0].val for r in results]


@do_across_groups
def get_project_ids(conn: BlitzGateway,
                    annotation: Optional[int] = None,
                    across_groups: Optional[bool] = True) -> List[int]:
    """Return a list with IDs for all available Projects.

    Parameters
    ----------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    annotation : int, optional
        ID of Annotation from which to return project IDs. This will return IDs
        of all projects linked to the specified annotation.
    across_groups : bool, optional
        Defines cross-group behavior of function - set to
        ``False`` to disable it.

    Returns
    -------
    proj_ids : list of ints
        List of project IDs accessible by current user.

    Examples
    --------
    # Return IDs of all projects accessible by current user:

    >>> proj_ids = get_project_ids(conn)

    # Return IDs of all projects annotated with tag id 576:

    >>> proj_ids = get_project_ids(conn, annotation=576)
    """

    q = conn.getQueryService()
    params = Parameters()

    if annotation is not None:
        if not isinstance(annotation, int):
            raise TypeError('Annotation ID must be integer')
        params.map = {"annotation": rlong(annotation)}
        results = q.projection(
            "SELECT l.parent.id FROM ProjectAnnotationLink l"
            " WHERE l.child.id=:annotation",
            params,
            conn.SERVICE_OPTS
            )
        proj_ids = [r[0].val for r in results]
    else:
        proj_ids = []
        for p in conn.listProjects():
            proj_ids.append(p.getId())
    return proj_ids


@do_across_groups
def get_dataset_ids(conn: BlitzGateway, project: Optional[int] = None,
                    annotation: Optional[int] = None,
                    across_groups: Optional[bool] = True) -> List[int]:
    """Return a list of dataset ids based on project ID.

    If no project or annotation is specified, function will return
    orphan datasets.

    Parameters
    ----------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    project : int, optional
        ID of Project from which to return dataset IDs. This will return IDs of
        all datasets contained in the specified Project.
    annotation : int, optional
        ID of Annotation from which to return dataset IDs. This will return IDs
        of all datasets linked to the specified annotation.
    across_groups : bool, optional
        Defines cross-group behavior of function - set to
        ``False`` to disable it.

    Returns
    -------
    ds_ids : list of ints
        List of dataset IDs contained in the specified project.

    Examples
    --------
    # Return orphaned datasets:

    >>> orphans = get_dataset_ids(conn)

    # Return IDs of all datasets from Project with ID 224:

    >>> ds_ids = get_dataset_ids(conn, project=224)
    """
    arg_counter = 0
    for arg in [project, annotation]:
        if arg is not None:
            arg_counter += 1
    if arg_counter > 1:
        raise ValueError('Only one of Project/Annotation'
                         ' can be specified')

    q = conn.getQueryService()
    params = Parameters()

    if project is not None:
        if not isinstance(project, int):
            raise TypeError('Project ID must be integer')
        params.map = {"project": rlong(project)}
        results = q.projection(
            "SELECT d.id FROM Project p"
            " JOIN p.datasetLinks pdl"
            " JOIN pdl.child d"
            " WHERE p.id=:project",
            params,
            conn.SERVICE_OPTS
            )
    elif annotation is not None:
        if not isinstance(annotation, int):
            raise TypeError('Annotation ID must be integer')
        params.map = {"annotation": rlong(annotation)}
        results = q.projection(
            "SELECT l.parent.id FROM DatasetAnnotationLink l"
            " WHERE l.child.id=:annotation",
            params,
            conn.SERVICE_OPTS
            )
    else:
        results = q.projection(
            "SELECT d.id FROM Dataset d"
            " WHERE NOT EXISTS ("
            " SELECT pdl FROM ProjectDatasetLink pdl"
            " WHERE pdl.child=d.id"
            " )",
            params,
            conn.SERVICE_OPTS
            )
    return [r[0].val for r in results]


@do_across_groups
def get_screen_ids(conn: BlitzGateway, annotation: Optional[int] = None,
                   across_groups: Optional[bool] = True) -> List[int]:
    """Return a list with IDs for all available Screens.

    Parameters
    ----------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    annotation : int, optional
        ID of Annotation from which to return screen IDs. This will return IDs
        of all screens linked to the specified annotation.
    across_groups : bool, optional
        Defines cross-group behavior of function - set to
        ``False`` to disable it.

    Returns
    -------
    scrn_ids : list of ints
        List of screen IDs accessible by current user.

    Examples
    --------
    # Return IDs of all screens accessible by current user:

    >>> scrn_ids = get_screen_ids(conn)

    # Return IDs of all screens annotated with tag id 913:

    >>> proj_ids = get_screen_ids(conn, annotation=913)
    """

    q = conn.getQueryService()
    params = Parameters()

    if annotation is not None:
        if not isinstance(annotation, int):
            raise TypeError('Annotation ID must be integer')
        params.map = {"annotation": rlong(annotation)}
        results = q.projection(
            "SELECT l.parent.id FROM ScreenAnnotationLink l"
            " WHERE l.child.id=:annotation",
            params,
            conn.SERVICE_OPTS
            )
        scrn_ids = [r[0].val for r in results]
    else:
        scrn_ids = []
        for s in conn.listScreens():
            scrn_ids.append(s.getId())
    return scrn_ids


@do_across_groups
def get_plate_ids(conn: BlitzGateway, screen: Optional[int] = None,
                  annotation: Optional[int] = None,
                  across_groups: Optional[bool] = True) -> List[int]:
    """Return a list of plate ids based on screen ID.

    If no screen is specified, function will return orphan plates.

    Parameters
    ----------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    screen : int, optional
        ID of Screen from which to return plate IDs. This will return IDs of
        all plates contained in the specified Screen.
    annotation : int, optional
        ID of Annotation from which to return plate IDs. This will return IDs
        of all plates linked to the specified annotation.
    across_groups : bool, optional
        Defines cross-group behavior of function - set to
        ``False`` to disable it.

    Returns
    -------
    pl_ids : list of ints
        List of plates IDs contained in the specified screen.

    Examples
    --------
    # Return orphaned plates:

    >>> orphans = get_plate_ids(conn)

    # Return IDs of all plates from Screen with ID 224:

    >>> pl_ids = get_plate_ids(conn, screen=224)
    """
    arg_counter = 0
    for arg in [screen, annotation]:
        if arg is not None:
            arg_counter += 1
    if arg_counter > 1:
        raise ValueError('Only one of Screen/Annotation'
                         ' can be specified')

    q = conn.getQueryService()
    params = Parameters()

    if screen is not None:
        if not isinstance(screen, int):
            raise TypeError('Screen ID must be integer')
        params.map = {"screen": rlong(screen)}
        results = q.projection(
            "SELECT p.id FROM Screen s"
            " JOIN s.plateLinks spl"
            " JOIN spl.child p"
            " WHERE s.id=:screen",
            params,
            conn.SERVICE_OPTS
            )
    elif annotation is not None:
        if not isinstance(annotation, int):
            raise TypeError('Annotation ID must be integer')
        params.map = {"annotation": rlong(annotation)}
        results = q.projection(
            "SELECT l.parent.id FROM PlateAnnotationLink l"
            " WHERE l.child.id=:annotation",
            params,
            conn.SERVICE_OPTS
            )
    else:
        results = q.projection(
            "SELECT p.id FROM Plate p"
            " WHERE NOT EXISTS ("
            " SELECT spl FROM ScreenPlateLink spl"
            " WHERE spl.child=p.id"
            " )",
            params,
            conn.SERVICE_OPTS
            )
    return [r[0].val for r in results]


@do_across_groups
def get_well_ids(conn: BlitzGateway, screen: Optional[int] = None,
                 plate: Optional[int] = None, annotation: Optional[int] = None,
                 across_groups: Optional[bool] = True) -> List[int]:
    """Return a list of well ids based on a container

    Parameters
    ----------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    screen : int, optional
        ID of Screen from which to return well IDs. This will return IDs of
        all wells contained in the specified Screen.
    plate : int, optional
        ID of Plate from which to return well IDs. This will return IDs of
        all wells belonging to the specified Plate.
    annotation : int, optional
        ID of Annotation from which to return well IDs. This will return IDs
        of all wells linked to the specified annotation.
    across_groups : bool, optional
        Defines cross-group behavior of function - set to
        ``False`` to disable it.

    Returns
    -------
    wl_ids : list of ints
        List of wells IDs contained in the specified container.

    Examples
    --------
    # Return IDs of all wells from Screen with ID 224:

    >>> wl_ids = get_well_ids(conn, screen=224)
    """
    arg_counter = 0
    for arg in [screen, plate, annotation]:
        if arg is not None:
            arg_counter += 1
    if arg_counter > 1:
        raise ValueError('Only one of Screen/Plate/Annotation'
                         ' can be specified')
    elif arg_counter == 0:
        raise ValueError('One of Screen/Plate/Annotation'
                         ' must be specified')

    q = conn.getQueryService()
    params = Parameters()

    if screen is not None:
        if not isinstance(screen, int):
            raise TypeError('Screen ID must be integer')
        params.map = {"screen": rlong(screen)}
        results = q.projection(
            "SELECT w.id FROM Screen s"
            " JOIN s.plateLinks spl"
            " JOIN spl.child p"
            " JOIN p.wells w"
            " WHERE s.id=:screen",
            params,
            conn.SERVICE_OPTS
            )
    elif plate is not None:
        if not isinstance(plate, int):
            raise TypeError('Plate ID must be integer')
        params.map = {"plate": rlong(plate)}
        results = q.projection(
            "SELECT w.id FROM Plate p"
            " JOIN p.wells w"
            " WHERE p.id=:plate",
            params,
            conn.SERVICE_OPTS
            )
    elif annotation is not None:
        if not isinstance(annotation, int):
            raise TypeError('Annotation ID must be integer')
        params.map = {"annotation": rlong(annotation)}
        results = q.projection(
            "SELECT l.parent.id FROM WellAnnotationLink l"
            " WHERE l.child.id=:annotation",
            params,
            conn.SERVICE_OPTS
            )
    return [r[0].val for r in results]


@do_across_groups
def get_plate_acquisition_ids(
    conn: BlitzGateway, screen: Optional[int] = None,
    plate: Optional[int] = None, annotation: Optional[int] = None,
    across_groups: Optional[bool] = True
) -> List[int]:
    """Return a list of plate acquisition ids based on a container

    Parameters
    ----------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    screen : int, optional
        ID of Screen from which to return plate acquisition IDs.
        This will return IDs of all plate acquisitions contained
        in the specified Screen.
    plate : int, optional
        ID of Plate from which to return plate acquisition IDs.
        This will return IDs of all plate acquisitions belonging
        to the specified Plate.
    annotation : int, optional
        ID of Annotation from which to return run IDs. This will return IDs
        of all runs linked to the specified annotation.
    across_groups : bool, optional
        Defines cross-group behavior of function - set to
        ``False`` to disable it.

    Returns
    -------
    plate_acquisition_ids : list of ints
        List of plate acquisitions IDs contained in the specified container.

    Examples
    --------
    # Return IDs of all plate acquisitions from Screen with ID 224:

    >>> plate_acquisition_ids = get_plate_acquisition_ids(conn, screen=224)
    """
    arg_counter = 0
    for arg in [screen, plate, annotation]:
        if arg is not None:
            arg_counter += 1
    if arg_counter > 1:
        raise ValueError('Only one of Screen/Plate/Annotation'
                         ' can be specified')
    elif arg_counter == 0:
        raise ValueError('One of Screen/Plate/Annotation'
                         ' must be specified')

    q = conn.getQueryService()
    params = Parameters()

    if screen is not None:
        if not isinstance(screen, int):
            raise TypeError('Screen ID must be integer')
        params.map = {"screen": rlong(screen)}
        results = q.projection(
            "SELECT r.id FROM Screen s"
            " JOIN s.plateLinks spl"
            " JOIN spl.child p"
            " JOIN p.plateAcquisitions r"
            " WHERE s.id=:screen",
            params,
            conn.SERVICE_OPTS
            )
    elif plate is not None:
        if not isinstance(plate, int):
            raise TypeError('Plate ID must be integer')
        params.map = {"plate": rlong(plate)}
        results = q.projection(
            "SELECT r.id FROM Plate p"
            " JOIN p.plateAcquisitions r"
            " WHERE p.id=:plate",
            params,
            conn.SERVICE_OPTS
            )
    elif annotation is not None:
        if not isinstance(annotation, int):
            raise TypeError('Annotation ID must be integer')
        params.map = {"annotation": rlong(annotation)}
        results = q.projection(
            "SELECT l.parent.id FROM PlateAcquisitionAnnotationLink l"
            " WHERE l.child.id=:annotation",
            params,
            conn.SERVICE_OPTS
            )
    return [r[0].val for r in results]


@do_across_groups
def get_map_annotation_ids(conn: BlitzGateway, object_type: str,
                           object_id: int, ns: Optional[str] = None,
                           across_groups: Optional[bool] = True) -> List[int]:
    """Get IDs of map annotations associated with an object

    Parameters
    ----------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    object_type : str
        OMERO object type, passed to ``BlitzGateway.getObject``
    object_id : int
        ID of object of ``object_type``.
    ns : str, optional
        Namespace with which to filter results
    across_groups : bool, optional
        Defines cross-group behavior of function - set to
        ``False`` to disable it.

    Returns
    -------
    map_ann_ids : list of ints

    Examples
    --------
    # Return IDs of all map annotations belonging to an image:

    >>> map_ann_ids = get_map_annotation_ids(conn, 'Image', 42)

    # Return IDs of map annotations with namespace "test" linked to a Dataset:

    >>> map_ann_ids = get_map_annotation_ids(conn, 'Dataset', 16, ns='test')
    """
    if type(object_type) is not str:
        raise TypeError('Object type must be a string')
    if type(object_id) is not int:
        raise TypeError('Object id must be an integer')
    if ns is not None and type(ns) is not str:
        raise TypeError('Namespace must be a string or None')

    target_object = conn.getObject(object_type, object_id)
    map_ann_ids = []
    for ann in target_object.listAnnotations(ns):
        if ann.OMERO_TYPE is MapAnnotationI:
            map_ann_ids.append(ann.getId())
    return map_ann_ids


@do_across_groups
def get_tag_ids(conn: BlitzGateway, object_type: str, object_id: int,
                ns: Optional[str] = None,
                across_groups: Optional[bool] = True) -> List[int]:
    """Get IDs of tag annotations associated with an object

    Parameters
    ----------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    object_type : str
        OMERO object type, passed to ``BlitzGateway.getObject``
    object_id : int
        ID of object of ``object_type``.
    ns : str, optional
        Namespace with which to filter results
    across_groups : bool, optional
        Defines cross-group behavior of function - set to
        ``False`` to disable it.

    Returns
    -------
    tag_ids : list of ints

    Examples
    --------
    # Return IDs of all tags linked to an image:

    >>> tag_ids = get_tag_ids(conn, 'Image', 42)

    # Return IDs of tags with namespace "test" linked to a Dataset:

    >>> tag_ids = get_tag_ids(conn, 'Dataset', 16, ns='test')
    """
    if type(object_type) is not str:
        raise TypeError('Object type must be a string')
    if type(object_id) is not int:
        raise TypeError('Object id must be an integer')
    if ns is not None and type(ns) is not str:
        raise TypeError('Namespace must be a string or None')

    target_object = conn.getObject(object_type, object_id)
    tag_ids = []
    for ann in target_object.listAnnotations(ns):
        if ann.OMERO_TYPE is TagAnnotationI:
            tag_ids.append(ann.getId())
    return tag_ids


@do_across_groups
def get_comment_annotation_ids(conn: BlitzGateway, object_type: str,
                               object_id: int, ns: Optional[str] = None,
                               across_groups: Optional[bool] = True
                               ) -> List[int]:
    """Get IDs of comment annotations associated with an object

    Parameters
    ----------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    object_type : str
        OMERO object type, passed to ``BlitzGateway.getObject``
    object_id : int
        ID of object of ``object_type``.
    ns : str, optional
        Namespace with which to filter results
    across_groups : bool, optional
        Defines cross-group behavior of function - set to
        ``False`` to disable it.

    Returns
    -------
    comment_ids : list of ints

    Examples
    --------
    # Return IDs of all comments linked to an image:

    >>> comment_ids = get_comment_ids(conn, 'Image', 42)

    # Return IDs of comments with namespace "test" linked to a Dataset:

    >>> tag_ids = get_tag_ids(conn, 'Dataset', 16, ns='test')
    """
    if type(object_type) is not str:
        raise TypeError('Object type must be a string')
    if type(object_id) is not int:
        raise TypeError('Object id must be an integer')
    if ns is not None and type(ns) is not str:
        raise TypeError('Namespace must be a string or None')

    target_object = conn.getObject(object_type, object_id)
    comment_ids = []
    for ann in target_object.listAnnotations(ns):
        if ann.OMERO_TYPE is CommentAnnotationI:
            comment_ids.append(ann.getId())
    return comment_ids


@do_across_groups
def get_file_annotation_ids(conn: BlitzGateway, object_type: str,
                            object_id: int, ns: Optional[str] = None,
                            across_groups: Optional[bool] = True) -> List[int]:
    """Get IDs of file annotations associated with an object

    Parameters
    ----------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    object_type : str
        OMERO object type, passed to ``BlitzGateway.getObject``
    object_id : int
        ID of object of ``object_type``.
    ns : str, optional
        Namespace with which to filter results
    across_groups : bool, optional
        Defines cross-group behavior of function - set to
        ``False`` to disable it.

    Returns
    -------
    file_ann_ids : list of ints

    Examples
    --------
    # Return IDs of all file annotations linked to an image:

    >>> file_ann_ids = get_file_annotation_ids(conn, 'Image', 42)

    # Return IDs of file annotations with namespace "test" linked to a Dataset:

    >>> file_ann_ids = get_file_annotation_ids(conn, 'Dataset', 16, ns='test')
    """
    if type(object_type) is not str:
        raise TypeError('Object type must be a string')
    if type(object_id) is not int:
        raise TypeError('Object id must be an integer')
    if ns is not None and type(ns) is not str:
        raise TypeError('Namespace must be a string or None')

    target_object = conn.getObject(object_type, object_id)
    file_ann_ids = []
    for ann in target_object.listAnnotations(ns):
        if isinstance(ann, FileAnnotationWrapper):
            file_ann_ids.append(ann.getId())
    return file_ann_ids


@do_across_groups
def get_well_id(conn: BlitzGateway, plate_id: int, row: int, column: int,
                across_groups: Optional[bool] = True) -> Union[int, None]:
    """Get ID of well based on plate ID, row, and column

    Parameters
    ----------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    plate_id : int
        ID of plate for which the well ID is needed
    row : int
        Row of well (zero-based indexing)
    column : int
        Column of well (zero-based indexing)

    Returns
    -------
    well_id : int
        ID of well being queried.
    """
    if not isinstance(plate_id, int):
        raise TypeError('Plate ID must be an integer')
    if not isinstance(row, int):
        raise TypeError('Row index must be an integer')
    if not isinstance(column, int):
        raise TypeError('Column index must be an integer')
    q = conn.getQueryService()
    params = Parameters()
    params.map = {"plate": rlong(plate_id),
                  "row": rint(row),
                  "column": rint(column)}
    results = q.projection(
        "SELECT w.id FROM Plate pl"
        " JOIN pl.wells w"
        " WHERE pl.id=:plate"
        " AND w.row=:row"
        " AND w.column=:column",
        params,
        conn.SERVICE_OPTS
        )
    if len(results) == 0:
        return None
    return [r[0].val for r in results][0]


@do_across_groups
def get_roi_ids(conn: BlitzGateway, image_id: int,
                across_groups: Optional[bool] = True) -> List[int]:
    """Get IDs of ROIs associated with an Image

    Parameters
    ----------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    image_id : int
        ID of ``Image``.
    across_groups : bool, optional
        Defines cross-group behavior of function - set to
        ``False`` to disable it.

    Returns
    -------
    roi_ids : list of ints

    Examples
    --------
    # Return IDs of all ROIs linked to an image:

    >>> roi_ids = get_roi_ids(conn, 42)

    """
    if not isinstance(image_id, int):
        raise TypeError('Image ID must be an integer')
    roi_ids = []
    roi_svc = conn.getRoiService()
    roi_list = roi_svc.findByImage(image_id, None)
    for roi in roi_list.rois:
        roi_ids.append(roi.id.val)
    return roi_ids


@do_across_groups
def get_shape_ids(conn: BlitzGateway, roi_id: int,
                  across_groups: Optional[bool] = True
                  ) -> Union[List[int], None]:
    """Get IDs of shapes associated with an ROI

    Parameters
    ----------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    roi_id : int
        ID of ``ROI``.
    across_groups : bool, optional
        Defines cross-group behavior of function - set to
        ``False`` to disable it.

    Returns
    -------
    shape_ids : list of ints

    Examples
    --------
    # Return IDs of all shapes linked to an ROI:

    >>> shape_ids = get_shape_ids(conn, 4222)

    """
    if not isinstance(roi_id, int):
        raise TypeError('ROI ID must be an integer')
    q = conn.getQueryService()
    params = Parameters()
    params.map = {"roi_id": rlong(roi_id)}
    results = q.projection(
        "SELECT s.id FROM Shape s"
        " WHERE s.roi.id=:roi_id",
        params,
        conn.SERVICE_OPTS
        )
    if len(results) == 0:
        return None
    return [r[0].val for r in results]


@do_across_groups
def get_map_annotation(conn: BlitzGateway, map_ann_id: int,
                       across_groups: Optional[bool] = True) -> dict:
    """Get the value of a map annotation object

    Parameters
    ----------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    map_ann_id : int
        ID of map annotation to get.
    across_groups : bool, optional
        Defines cross-group behavior of function - set to
        ``False`` to disable it.

    Returns
    -------
    kv_dict : dict
        The value of the specified map annotation object, as a Python dict.
        If kv-pairs with the same key exist, the corresponding dict value
        will be a list.

    Examples
    --------
    >>> ma_dict = get_map_annotation(conn, 62)
    >>> print(ma_dict)
    {'testkey': 'testvalue', 'testkey2': ['testvalue2'. 'testvalue3']}
    """
    if type(map_ann_id) is not int:
        raise TypeError('Map annotation ID must be an integer')

    map_annotation_dict = {}

    map_annotation = conn.getObject('MapAnnotation', map_ann_id).getValue()

    for item in map_annotation:
        if item[0] in map_annotation_dict:
            if not isinstance(map_annotation_dict[item[0]], list):
                map_annotation_dict[item[0]] = [map_annotation_dict[item[0]]]
            map_annotation_dict[item[0]].append(item[1])
        else:
            map_annotation_dict[item[0]] = item[1]

    return map_annotation_dict


@do_across_groups
def get_tag(conn: BlitzGateway, tag_id: int,
            across_groups: Optional[bool] = True) -> str:
    """Get the value of a tag annotation object

    Parameters
    ----------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    tag_id : int
        ID of tag annotation to get.
    across_groups : bool, optional
        Defines cross-group behavior of function - set to
        ``False`` to disable it.

    Returns
    -------
    tag : str
        The value of the specified tag annotation object.

    Examples
    --------
    >>> tag = get_tag(conn, 62)
    >>> print(tag)
    This_is_a_tag
    """
    if type(tag_id) is not int:
        raise TypeError('Tag ID must be an integer')

    return conn.getObject('TagAnnotation', tag_id).getValue()


@do_across_groups
def get_comment_annotation(conn: BlitzGateway, comment_id: int,
                           across_groups: Optional[bool] = True) -> str:
    """Get the value of a comment annotation object

    Parameters
    ----------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    comment_id : int
        ID of comment annotation to get.
    across_groups : bool, optional
        Defines cross-group behavior of function - set to
        ``False`` to disable it.

    Returns
    -------
    comment : str
        The value of the specified tag annotation object.

    Examples
    --------
    >>> comment = get_tag(conn, 62)
    >>> print(comment)
    This is a comment
    """
    if type(comment_id) is not int:
        raise TypeError('Comment ID must be an integer')

    return conn.getObject('CommentAnnotation', comment_id).getValue()


@do_across_groups
def get_file_annotation(conn: BlitzGateway, file_ann_id: int,
                        folder_path: Optional[str] = None,
                        across_groups: Optional[bool] = True) -> str:
    """Get the value of a file annotation object

    Parameters
    ----------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    file_ann_id : int
        ID of file annotation to get.
    folder_path : str
        Path where file annotation will be saved. Defaults to local script
        directory.
    across_groups : bool, optional
        Defines cross-group behavior of function - set to
        ``False`` to disable it.

    Returns
    -------
    file_path : str
        The path to the created file.

    Examples
    --------
    >>> attch_path = get_file_annotation(conn,
    ...                                  62,
    ...                                  folder_path='/home/user/Downloads')
    >>> print(attch_path)
    '/home/user/Downloads/attachment.txt'
    """
    if type(file_ann_id) is not int:
        raise TypeError('File annotation ID must be an integer')

    if not folder_path or not os.path.exists(folder_path):
        folder_path = os.path.dirname(__file__)
    ann = conn.getObject('FileAnnotation', file_ann_id)
    file_path = os.path.join(folder_path, ann.getFile().getName())
    with open(str(file_path), 'wb') as f:
        for chunk in ann.getFileInChunks():
            f.write(chunk)
    return file_path


def get_group_id(conn: BlitzGateway, group_name: str) -> Union[int, None]:
    """Get ID of a group based on group name.

    Must be an exact match. Case sensitive.

    Parameters
    ----------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    group_name : str
        Name of the group for which an ID is to be returned.

    Returns
    -------
    group_id : int
        ID of the OMERO group. Returns `None` if group cannot be found.

    Examples
    --------
    >>> get_group_id(conn, "Research IT")
    304
    """
    if type(group_name) is not str:
        raise TypeError('OMERO group name must be a string')

    try:
        g = conn.c.sf.getAdminService().lookupGroup(group_name)
        return g.id.val
    except ApiUsageException:
        pass
    return None


def get_user_id(conn: BlitzGateway, user_name: str) -> Union[int, None]:
    """Get ID of a user based on user name.

    Must be an exact match. Case sensitive.

    Parameters
    ----------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    user_name : str
        Name of the user for which an ID is to be returned.

    Returns
    -------
    user_id : int
        ID of the OMERO user. Returns `None` if group cannot be found.

    Examples
    --------
    >>> get_user_id(conn, "jaxl")
    35
    """
    if type(user_name) is not str:
        raise TypeError('OMERO user name must be a string')

    for u in conn.containedExperimenters(1):
        if u.getName() == user_name:
            return u.getId()
    return None


@do_across_groups
def get_original_filepaths(
    conn: BlitzGateway, image_id: int,
    fpath: Optional[Literal["client", "repo"]] = 'repo',
    across_groups: Optional[bool] = True
) -> List[str]:
    """Get paths to original files for specified image.

    Parameters
    ----------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    image_id : int
        ID of image for which filepath info is to be returned.
    fpath : {'repo', 'client'}, optional
        Specify whether you want to return path to file in the managed
        repository ('repo') or the path from which the image was imported
        ('client'). The latter is useful for images that were imported by
        the "in place" method. Defaults to 'repo'.
    across_groups : bool, optional
        Defines cross-group behavior of function - set to
        ``False`` to disable it.

    Notes
    -----
    The ManagedRepository ('repo') paths are relative, whereas the client paths
    are absolute.

    The client path may not be accessible if the image was not imported using
    "in place" imports (e.g., ``transfer=ln_s``).

    Returns
    -------
    original_filepaths : list of str

    Examples
    --------
    # Return (relative) path of file in ManagedRepository:

    >>> get_original_filepaths(conn, 745)
    ['djme_2/2020-06/16/13-38-36.468/PJN17_083_07.ndpi']

    # Return client path (location of file when it was imported):

    >>> get_original_filepaths(conn, 2201, fpath='client')
    ['/client/omero/smith_lab/stack2/PJN17_083_07.ndpi']

    """
    if type(image_id) is not int:
        raise TypeError('Image ID must be an integer')

    q = conn.getQueryService()
    params = Parameters()
    params.map = {"imid": rlong(image_id)}

    if fpath == 'client':
        results = q.projection(
            "SELECT fe.clientPath"
            " FROM Image i"
            " JOIN i.fileset f"
            " JOIN f.usedFiles fe"
            " WHERE i.id=:imid",
            params,
            conn.SERVICE_OPTS
            )
        results = ['/' + r[0].val for r in results]
    elif fpath == 'repo':
        results = q.projection(
            "SELECT o.path||o.name"
            " FROM Image i"
            " JOIN i.fileset f"
            " JOIN f.usedFiles fe"
            " JOIN fe.originalFile o"
            " WHERE i.id=:imid",
            params,
            conn.SERVICE_OPTS
            )
        results = [r[0].val for r in results]
    else:
        raise ValueError("Parameter fpath must be 'client' or 'repo'")

    return results


@do_across_groups
def get_series_index(conn: BlitzGateway, image_id: int,
                     across_groups: Optional[bool] = True
                     ) -> int:
    """Get series index for an Image inside a fileset.

    Parameters
    ----------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    image_id : int
        ID of ``Image``.
    across_groups : bool, optional
        Defines cross-group behavior of function - set to
        ``False`` to disable it.

    Returns
    -------
    series_idx : int
        Index for specified image inside its Fileset as
        provided by Bioformats. In addition to a target
        file path, this allows for specific access to an
        individual image using Bioformats. If image was created
        without an original file (i.e. directly from pixels),
        returns -1.

    Examples
    --------
    # Return series index for an Image generated from a
    multiseries file (in this example, the third image):

    >>> series_idx = get_series_index(conn, 42)
    2
    """

    if type(image_id) is not int:
        raise TypeError('Image ID must be an integer')

    q = conn.getQueryService()
    params = Parameters()
    params.map = {"imid": rlong(image_id)}

    results = q.projection(
        "SELECT i.series"
        " FROM Image i"
        " JOIN i.fileset f"
        " JOIN f.usedFiles fe"
        " WHERE i.id=:imid AND index(fe)=0",
        params,
        conn.SERVICE_OPTS
        )
    if results:
        series_idx = results[0][0].val
    else:
        series_idx = -1
    return series_idx


@do_across_groups
def get_pyramid_levels(conn: BlitzGateway, image_id: int,
                       across_groups: Optional[bool] = True
                       ) -> List[Tuple[int, ...]]:
    """Get number of pyramid levels associated with an Image

    Parameters
    ----------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    image_id : int
        ID of ``Image``.
    across_groups : bool, optional
        Defines cross-group behavior of function - set to
        ``False`` to disable it.

    Returns
    -------
    levels : list of tuples
        Pyramidal levels available for this image, with number of
        pixels for X and Y axes.

    Examples
    --------
    # Return pyramid levels associated to an image:

    >>> lvls = get_pyramid_levels(conn, 42)
    [(2048, 1600), (1024, 800), (512, 400), (256, 200)]

    """
    image = conn.getObject("image", image_id)
    pix = image._conn.c.sf.createRawPixelsStore()
    pid = image.getPixelsId()
    pix.setPixelsId(pid, False)
    levels: List[Tuple[int, ...]]
    levels = [(r.sizeX, r.sizeY) for r in pix.getResolutionDescriptions()]
    pix.close()
    return levels


@do_across_groups
def get_table(conn: BlitzGateway, file_ann_id: int,
              across_groups: Optional[bool] = True
              ) -> Any:
    """Get a table from its FileAnnotation object.

    Parameters
    ----------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    file_ann_id : int
        ID of FileAnnotation table to get.
    across_groups : bool, optional
        Defines cross-group behavior of function - set to
        ``False`` to disable it.

    Returns
    -------
    table : object
        Object containing the actual table. It can be either a list of
        row-lists or a pandas Dataframe in case the optional pandas dependency
        was installed.

    Examples
    --------
    >>> table = get_table(conn, 62)
    >>> print(table[0])
    ['ID', 'X', 'Y']
    """
    if type(file_ann_id) is not int:
        raise TypeError('File annotation ID must be an integer')
    ann = conn.getObject('FileAnnotation', file_ann_id)
    table = None
    if ann:
        orig_table_file = conn.getObject('OriginalFile', ann.getFile().id)
        resources = conn.c.sf.sharedResources()
        try:
            table_obj = resources.openTable(orig_table_file._obj)
            table = _create_table(table_obj)
            table_obj.close()
        except InternalException:
            logging.warning(f" FileAnnotation {file_ann_id} is not a table.")
    else:
        logging.warning(f' FileAnnotation {file_ann_id} does not exist.')
    return table


@do_across_groups
def get_shape(conn: BlitzGateway, shape_id: int,
              across_groups: Optional[bool] = True
              ) -> ezShape:
    """Get an ezomero shape object from an OMERO Shape id

    Parameters
    ----------
    conn : ``omero.gateway.BlitzGateway`` object
        OMERO connection.
    shape_id : int
        ID of shape to get.
    across_groups : bool, optional
        Defines cross-group behavior of function - set to
        ``False`` to disable it.

    Returns
    -------
    shape : obj
        An object of one of ezomero shape classes

    Notes
    -------
    ``fill_color`` for the Shape defaults to (0, 0, 0, 0) in case the original
    Shape doesn't have one.
    ``stroke_color`` for the Shape defaults to (255, 255, 0, 255) in case the
    original Shape doesn't have one.
    ``stroke_width`` for the Shape defaults to 1 in case the original Shape
    doesn't have one.
    Examples
    --------
    >>> shape = get_shape(conn, 634443)

    """
    if not isinstance(shape_id, int):
        raise TypeError('Shape ID must be an integer')
    omero_shape = conn.getObject('Shape', shape_id)
    return _omero_shape_to_shape(omero_shape)


def _create_table(table_obj: Table
                  ) -> Any:
    if importlib.util.find_spec('pandas'):
        columns = []
        for col in table_obj.getHeaders():
            columns.append(col.name)
        table = pd.DataFrame(columns=columns)
        rowCount = table_obj.getNumberOfRows()
        data = table_obj.read(list(range(len(columns))), 0, rowCount)
        for col in data.columns:
            col_data = []
            for v in col.values:
                col_data.append(v)
            table[col.name] = col_data

    else:
        table = []
        columns = []
        data_lists = []
        for col in table_obj.getHeaders():
            columns.append(col.name)
        table.append(columns)
        rowCount = table_obj.getNumberOfRows()
        data = table_obj.read(list(range(len(columns))), 0, rowCount)
        for col in data.columns:
            col_data = []
            for v in col.values:
                col_data.append(v)
            data_lists.append(col_data)
        # transpose data_lists
        data_lists = [list(i) for i in zip(*data_lists)]
        for row in data_lists:
            table.append(row)

    return table


def _omero_shape_to_shape(omero_shape: Shape
                          ) -> ezShape:
    """ Helper function to convert ezomero shapes into omero shapes"""
    shape_type = omero_shape.ice_id().split("::omero::model::")[1]
    fill_color = _int_to_rgba(omero_shape.getFillColor(), True)
    stroke_color = _int_to_rgba(omero_shape.getStrokeColor(), False)
    try:
        stroke_width = omero_shape.getStrokeWidth().getValue()
    except AttributeError:
        stroke_width = 1
    try:
        z_val = omero_shape.theZ
    except AttributeError:
        z_val = None
    try:
        c_val = omero_shape.theC
    except AttributeError:
        c_val = None
    try:
        t_val = omero_shape.theT
    except AttributeError:
        t_val = None
    try:
        text = omero_shape.textValue
    except AttributeError:
        text = None
    try:
        mk_start = omero_shape.markerStart
    except AttributeError:
        mk_start = None
    try:
        mk_end = omero_shape.markerEnd
    except AttributeError:
        mk_end = None
    shape: Union[Point, Line, Rectangle, Ellipse, Polygon, Polyline, Label]
    if shape_type == "Point":
        x = omero_shape.x
        y = omero_shape.y
        shape = Point(x, y, z_val, c_val, t_val, text, fill_color,
                      stroke_color, stroke_width)
    elif shape_type == "Line":
        x1 = omero_shape.x1
        x2 = omero_shape.x2
        y1 = omero_shape.y1
        y2 = omero_shape.y2
        shape = Line(x1, y1, x2, y2, z_val, c_val, t_val, mk_start, mk_end,
                     text, fill_color, stroke_color, stroke_width)
    elif shape_type == "Rectangle":
        x = omero_shape.x
        y = omero_shape.y
        width = omero_shape.width
        height = omero_shape.height
        shape = Rectangle(x, y, width, height, z_val, c_val, t_val, text,
                          fill_color, stroke_color, stroke_width)
    elif shape_type == "Ellipse":
        x = omero_shape.x
        y = omero_shape.y
        radiusX = omero_shape.radiusX
        radiusY = omero_shape.radiusY
        shape = Ellipse(x, y, radiusX, radiusY, z_val, c_val, t_val, text,
                        fill_color, stroke_color, stroke_width)
    elif shape_type == "Polygon":
        omero_points = omero_shape.points.split()
        points = []
        for point in omero_points:
            coords = point.split(',')
            points.append((float(coords[0]), float(coords[1])))
        shape = Polygon(points, z_val, c_val, t_val, text, fill_color,
                        stroke_color, stroke_width)
    elif shape_type == "Polyline":
        omero_points = omero_shape.points.split()
        points = []
        for point in omero_points:
            coords = point.split(',')
            points.append((float(coords[0]), float(coords[1])))
        shape = Polyline(points, z_val, c_val, t_val, text, fill_color,
                         stroke_color, stroke_width)
    elif shape_type == "Label":
        x = omero_shape.x
        y = omero_shape.y
        fsize = omero_shape.getFontSize().getValue()
        shape = Label(x, y, text, fsize, z_val, c_val, t_val, fill_color,
                      stroke_color, stroke_width)
    else:
        err = 'The shape passed for the roi is not a valid shape type'
        raise TypeError(err)
    return shape


def _int_to_rgba(omero_val: Union[int, None], is_fill: bool) -> \
        Tuple[int, int, int, int]:
    """ Helper function returning the color as an Integer in RGBA encoding """
    if omero_val:
        if omero_val < 0:
            omero_val = omero_val + (2**32)
        r = omero_val >> 24
        g = omero_val - (r << 24) >> 16
        b = omero_val - (r << 24) - (g << 16) >> 8
        a = omero_val - (r << 24) - (g << 16) - (b << 8)
        return (r, g, b, a)
    else:
        if is_fill:
            return (0, 0, 0, 0)
        else:
            return (255, 255, 0, 255)
