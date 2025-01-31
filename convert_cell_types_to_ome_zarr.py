import pathlib
import argparse
import time
import numpy as np
import multiprocessing
from neuroglancer_interface.utils.multiprocessing_utils import (
    _winnow_process_list)

from neuroglancer_interface.utils.celltypes_utils import (
    get_class_lookup)

from neuroglancer_interface.utils.data_utils import (
    write_nii_file_list_to_ome_zarr,
    write_summed_nii_files_to_group)

def write_summed_object(
        cluster_to_path,
        obj_to_clusters,
        root_group,
        downscale=2,
        n_processors=4,
        prefix=None):

    t0 = time.time()
    full_group_list = _get_valid_group_list(
                        obj_to_clusters=obj_to_clusters,
                        cluster_to_path=cluster_to_path)

    if len(full_group_list) == 0:
        return root_group

    if prefix is not None:
        parent_group = root_group.create_group(prefix)
    else:
        parent_group = root_group

    n_workers = max(1, n_processors-1)

    n_per_processor = max(1,
                          np.floor(len(full_group_list)/n_workers).astype(int))
    process_list = []
    for i0 in range(0, len(full_group_list), n_per_processor):
        i1 = min(i0+n_per_processor, len(full_group_list))
        group_list = full_group_list[i0:i1]
        p = multiprocessing.Process(
                target=_write_summed_object_worker,
                kwargs={'parent_group': parent_group,
                        'group_list': group_list,
                        'obj_to_clusters': obj_to_clusters,
                        'cluster_to_path': cluster_to_path,
                        'downscale': downscale})
        p.start()
        process_list.append(p)
        while len(process_list) >= n_workers:
            process_list = _winnow_process_list(process_list)

    for p in process_list:
        p.join()

    duration = time.time()-t0
    print(f"{prefix} took {duration:.2e} seconds")
    return root_group


def _write_summed_object_worker(
        parent_group,
        group_list,
        obj_to_clusters,
        cluster_to_path,
        downscale):

    for key in group_list:
        cluster_list = obj_to_clusters[key]
        file_path_list = [cluster_to_path[c] for c in cluster_list
                          if c in cluster_to_path]

        if len(file_path_list) > 0:
            group_name = key
            this_group = parent_group.create_group(group_name)
            write_summed_nii_files_to_group(
                file_path_list=file_path_list,
                group=this_group,
                downscale=downscale)

            print(f"wrote group {key}")


def _get_valid_group_list(
        obj_to_clusters,
        cluster_to_path):
    """
    Returns list of objects that have non-zero number
    of valid cluster files
    """
    raw_group_list = list(obj_to_clusters.keys())
    raw_group_list.sort()
    full_group_list = []
    for group in raw_group_list:
        cluster_list = obj_to_clusters[group]
        file_path_list = [cluster_to_path[c] for c in cluster_list
                          if c in cluster_to_path]
        if len(file_path_list) > 0:
            full_group_list.append(group)
    return full_group_list


def main():

    default_input = '/allen/programs/celltypes/workgroups/'
    default_input += 'rnaseqanalysis/mFISH/michaelkunst/MERSCOPES/'
    default_input += 'mouse/atlas/mouse_1/alignment/warpedCellTypes_Mouse1'

    default_anno = '/allen/programs/celltypes/'
    default_anno += 'workgroups/rnaseqanalysis/mFISH'
    default_anno += '/michaelkunst/MERSCOPES/mouse/cluster_anno.csv'

    parser = argparse.ArgumentParser(
                "Convert cell types to ome-zarr in the case where "
                "there are only .nii.gz files for clusters and these "
                "need to be summed to produce classes and subclasses")
    parser.add_argument('--output_dir', type=str, default=None)
    parser.add_argument('--input_dir', type=str, default=default_input)
    parser.add_argument('--annotation_path', type=str, default=default_anno)
    parser.add_argument('--clobber', default=False, action='store_true')
    parser.add_argument('--downscale', type=int, default=2)
    parser.add_argument('--n_processors', type=int, default=4)
    args = parser.parse_args()

    assert args.output_dir is not None
    assert args.input_dir is not None

    output_dir = pathlib.Path(args.output_dir)
    input_dir = pathlib.Path(args.input_dir)

    assert input_dir.is_dir()

    suffix = "_AppliedWarpAllSlc.nii.gz"

    (subclass_to_clusters,
     class_to_clusters,
     valid_clusters,
     desanitizer) = get_class_lookup(args.annotation_path)

    fpath_list = [n for n in input_dir.rglob('*nii.gz')]
    fpath_list.sort()
    cluster_name_list = []
    cluster_to_path = dict()
    for fpath in fpath_list:
        fname = fpath.name
        params = fname.split('_')
        cluster_name = fname.replace(f"{params[0]}_", "")
        cluster_name = cluster_name.replace(suffix, "")
        assert cluster_name in valid_clusters
        cluster_name_list.append(cluster_name)
        cluster_to_path[cluster_name] = fpath

    root_group = write_nii_file_list_to_ome_zarr(
            file_path_list=fpath_list,
            group_name_list=cluster_name_list,
            output_dir=args.output_dir,
            downscale=args.downscale,
            n_processors=args.n_processors,
            clobber=args.clobber,
            prefix="clusters")

    root_group = write_summed_object(
            cluster_to_path=cluster_to_path,
            obj_to_clusters=subclass_to_clusters,
            root_group=root_group,
            downscale=args.downscale,
            prefix="subclasses")

    root_group = write_summed_object(
            cluster_to_path=cluster_to_path,
            obj_to_clusters=class_to_clusters,
            root_group=root_group,
            downscale=args.downscale,
            prefix="classes")


if __name__ == "__main__":
    main()
