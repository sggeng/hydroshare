import os
import logging
import shutil
import subprocess
import zipfile

import xml.etree.ElementTree as ET
from lxml import etree

import gdal
from gdalconst import GA_ReadOnly

from functools import partial, wraps

from django.db import models, transaction
from django.core.exceptions import ValidationError
from django.forms.models import formset_factory
from django.template import Template, Context

from dominate.tags import div, legend, form, button

from hs_core.hydroshare import utils
from hs_core.hydroshare.resource import delete_resource_file
from hs_core.forms import CoverageTemporalForm, CoverageSpatialForm
from hs_core.models import ResourceFile, CoreMetaData

from hs_geo_raster_resource.models import CellInformation, BandInformation, OriginalCoverage, \
    GeoRasterMetaDataMixin
from hs_geo_raster_resource.forms import BandInfoForm, BaseBandInfoFormSet, BandInfoValidationForm

from hs_file_types import raster_meta_extract
from base import AbstractFileMetaData, AbstractLogicalFile


class GeoRasterFileMetaData(GeoRasterMetaDataMixin, AbstractFileMetaData):
    # the metadata element models used for this file type are from the raster resource type app
    # use the 'model_app_label' attribute with ContentType, do dynamically find the right element
    # model class from element name (string)
    model_app_label = 'hs_geo_raster_resource'

    @classmethod
    def get_metadata_model_classes(cls):
        metadata_model_classes = super(GeoRasterFileMetaData, cls).get_metadata_model_classes()
        metadata_model_classes['originalcoverage'] = OriginalCoverage
        metadata_model_classes['bandinformation'] = BandInformation
        metadata_model_classes['cellinformation'] = CellInformation
        return metadata_model_classes

    def get_metadata_elements(self):
        elements = super(GeoRasterFileMetaData, self).get_metadata_elements()
        elements += [self.cellInformation, self.originalCoverage]
        elements += list(self.bandInformations.all())
        return elements

    def get_html(self):
        """overrides the base class function to generate html needed to display metadata
        in view mode"""

        html_string = super(GeoRasterFileMetaData, self).get_html()
        if self.spatial_coverage:
            html_string += self.spatial_coverage.get_html()
        if self.originalCoverage:
            html_string += self.originalCoverage.get_html()

        html_string += self.cellInformation.get_html()
        if self.temporal_coverage:
            html_string += self.temporal_coverage.get_html()
        band_legend = legend("Band Information", cls="pull-left", style="margin-left:10px;")
        html_string += band_legend.render()
        for band_info in self.bandInformations:
            html_string += band_info.get_html()

        template = Template(html_string)
        context = Context({})
        return template.render(context)

    def get_html_forms(self, dataset_name_form=True, temporal_coverage=True, **kwargs):
        """overrides the base class function to generate html needed for metadata editing"""

        root_div = div("{% load crispy_forms_tags %}")
        with root_div:
            super(GeoRasterFileMetaData, self).get_html_forms()
            with div(cls="col-lg-6 col-xs-12", id="spatial-coverage-filetype"):
                with form(id="id-spatial-coverage-file-type",
                          action="{{ coverage_form.action }}",
                          method="post", enctype="multipart/form-data"):
                    div("{% crispy coverage_form %}")
                    with div(cls="row", style="margin-top:10px;"):
                        with div(cls="col-md-offset-10 col-xs-offset-6 "
                                     "col-md-2 col-xs-6"):
                            button("Save changes", type="button",
                                   cls="btn btn-primary pull-right",
                                   style="display: none;")

            with div(cls="col-lg-6 col-xs-12"):
                div("{% crispy orig_coverage_form %}")
            with div(cls="col-lg-6 col-xs-12"):
                div("{% crispy cellinfo_form %}")

            with div(cls="pull-left col-sm-12"):
                with div(cls="well", id="variables"):
                    with div(cls="row"):
                        div("{% for form in bandinfo_formset_forms %}")
                        with div(cls="col-sm-6 col-xs-12"):
                            with form(id="{{ form.form_id }}", action="{{ form.action }}",
                                      method="post", enctype="multipart/form-data"):
                                div("{% crispy form %}")
                                with div(cls="row", style="margin-top:10px;"):
                                    with div(cls="col-md-offset-10 col-xs-offset-6 "
                                                 "col-md-2 col-xs-6"):
                                        button("Save changes", type="button",
                                               cls="btn btn-primary pull-right btn-form-submit",
                                               style="display: none;")
                        div("{% endfor %}")

        template = Template(root_div.render())
        context_dict = dict()

        context_dict["orig_coverage_form"] = self.get_original_coverage_form()
        context_dict["cellinfo_form"] = self.get_cellinfo_form()
        temp_cov_form = self.get_temporal_coverage_form()

        update_action = "/hsapi/_internal/GeoRasterLogicalFile/{0}/{1}/{2}/update-file-metadata/"
        create_action = "/hsapi/_internal/GeoRasterLogicalFile/{0}/{1}/add-file-metadata/"
        spatial_cov_form = self.get_spatial_coverage_form(allow_edit=True)
        if self.spatial_coverage:
            form_action = update_action.format(self.logical_file.id, "coverage",
                                               self.spatial_coverage.id)
        else:
            form_action = create_action.format(self.logical_file.id, "coverage")

        spatial_cov_form.action = form_action

        if self.temporal_coverage:
            form_action = update_action.format(self.logical_file.id, "coverage",
                                               self.temporal_coverage.id)
            temp_cov_form.action = form_action
        else:
            form_action = create_action.format(self.logical_file.id, "coverage")
            temp_cov_form.action = form_action

        context_dict["coverage_form"] = spatial_cov_form
        context_dict["temp_form"] = temp_cov_form
        context_dict["bandinfo_formset_forms"] = self.get_bandinfo_formset().forms
        context = Context(context_dict)
        rendered_html = template.render(context)
        return rendered_html

    def get_cellinfo_form(self):
        return self.cellInformation.get_html_form(resource=None)

    def get_original_coverage_form(self):
        return OriginalCoverage.get_html_form(resource=None, element=self.originalCoverage,
                                              file_type=True, allow_edit=False)

    def get_bandinfo_formset(self):
        BandInfoFormSetEdit = formset_factory(
            wraps(BandInfoForm)(partial(BandInfoForm, allow_edit=True)),
            formset=BaseBandInfoFormSet, extra=0)
        bandinfo_formset = BandInfoFormSetEdit(
            initial=self.bandInformations.values(), prefix='BandInformation')

        for frm in bandinfo_formset.forms:
            if len(frm.initial) > 0:
                frm.action = "/hsapi/_internal/%s/%s/bandinformation/%s/update-file-metadata/" % (
                    "GeoRasterLogicalFile", self.logical_file.id, frm.initial['id'])
                frm.number = frm.initial['id']

        return bandinfo_formset

    @classmethod
    def validate_element_data(cls, request, element_name):
        """overriding the base class method"""

        if element_name.lower() not in [el_name.lower() for el_name
                                        in cls.get_supported_element_names()]:
            err_msg = "{} is nor a supported metadata element for Geo Raster file type"
            err_msg = err_msg.format(element_name)
            return {'is_valid': False, 'element_data_dict': None, "errors": err_msg}
        element_name = element_name.lower()
        if element_name == 'bandinformation':
            form_data = {}
            for field_name in BandInfoValidationForm().fields:
                matching_key = [key for key in request.POST if '-' + field_name in key][0]
                form_data[field_name] = request.POST[matching_key]
            element_form = BandInfoValidationForm(form_data)
        elif element_name == 'coverage' and 'start' not in request.POST:
            element_form = CoverageSpatialForm(data=request.POST)
        else:
            # element_name must be coverage
            # here we are assuming temporal coverage
            element_form = CoverageTemporalForm(data=request.POST)

        if element_form.is_valid():
            return {'is_valid': True, 'element_data_dict': element_form.cleaned_data}
        else:
            return {'is_valid': False, 'element_data_dict': None, "errors": element_form.errors}

    # TODO: delete the following method - not needed anymore
    def add_to_xml_container(self, container):
        """Generates xml+rdf representation of all metadata elements associated with this
        logical file type instance"""

        container_to_add_to = super(GeoRasterFileMetaData, self).add_to_xml_container(container)
        if self.originalCoverage:
            self.originalCoverage.add_to_xml_container(container_to_add_to)
        if self.cellInformation:
            self.cellInformation.add_to_xml_container(container_to_add_to)
        for bandinfo in self.bandInformations:
            bandinfo.add_to_xml_container(container_to_add_to)

    def get_xml(self, pretty_print=True):
        """Generates ORI+RDF xml for this aggregation metadata"""

        # get the xml root element and the xml element to which contains all other elements
        RDF_ROOT, container_to_add_to = super(GeoRasterFileMetaData, self)._get_xml_containers()

        if self.originalCoverage:
            self.originalCoverage.add_to_xml_container(container_to_add_to)
        if self.cellInformation:
            self.cellInformation.add_to_xml_container(container_to_add_to)
        for bandinfo in self.bandInformations:
            bandinfo.add_to_xml_container(container_to_add_to)

        return CoreMetaData.XML_HEADER + '\n' + etree.tostring(RDF_ROOT, pretty_print=pretty_print)


class GeoRasterLogicalFile(AbstractLogicalFile):
    metadata = models.OneToOneField(GeoRasterFileMetaData, related_name="logical_file")
    data_type = "GeographicRaster"

    @classmethod
    def get_allowed_uploaded_file_types(cls):
        """only .zip and .tif file can be set to this logical file group"""
        return [".zip", ".tif"]

    @classmethod
    def get_allowed_storage_file_types(cls):
        """file types allowed in this logical file group are: .tif and .vrt"""
        return [".tif", ".vrt"]

    @staticmethod
    def get_aggregation_display_name():
        return 'Geographic Raster Aggregation'

    @staticmethod
    def get_aggregation_type_name():
        return "GeographicRasterAggregation"

    @classmethod
    def create(cls):
        """this custom method MUST be used to create an instance of this class"""
        raster_metadata = GeoRasterFileMetaData.objects.create(keywords=[])
        return cls.objects.create(metadata=raster_metadata)

    @property
    def supports_resource_file_move(self):
        """resource files that are part of this logical file can't be moved"""
        return False

    @property
    def supports_resource_file_add(self):
        """doesn't allow a resource file to be added"""
        return False

    @property
    def supports_resource_file_rename(self):
        """resource files that are part of this logical file can't be renamed"""
        return False

    @property
    def supports_delete_folder_on_zip(self):
        """does not allow the original folder to be deleted upon zipping of that folder"""
        return False

    @classmethod
    def check_files_for_aggregation_type(cls, files):
        """Checks if the specified files can be used to set this aggregation type
        :param  files: a list of ResourceFile objects

        :return If the files meet the requirements of this aggregation type, then returns this
        aggregation class name, otherwise empty string.
        """
        if not files:
            # no files
            return ""

        for fl in files:
            if fl.extension.lower() not in cls.get_allowed_storage_file_types():
                return ""

        # check that there can be only one vrt file
        vrt_files = [f for f in files if f.extension.lower() == ".vrt"]
        if len(vrt_files) > 1:
            return ""

        # check if there are multiple tif files, then there has to be one vrt file
        tif_files = [f for f in files if f.extension.lower() == ".tif"]
        if len(tif_files) > 1:
            if len(vrt_files) != 1:
                return ""
        elif not tif_files:
            # there has to be at least one tif file
            return ""

        return cls.__name__

    @classmethod
    def set_file_type(cls, resource, user, file_id=None, folder_path=None):
        """ Sets a tif or zip resource file, or a folder to GeoRasterLogicalFile type """

        # had to import it here to avoid import loop
        from hs_core.views.utils import create_folder

        log = logging.getLogger()
        res_file, folder_path = cls._validate_set_file_type_inputs(resource, file_id, folder_path)
        file_name = res_file.file_name
        # get file name without the extension - needed for naming the aggregation folder
        base_file_name = file_name[:-len(res_file.extension)]
        file_folder = res_file.file_folder
        upload_folder = ''
        # get the file from irods to temp dir
        temp_file = utils.get_file_from_irods(res_file)
        temp_dir = os.path.dirname(temp_file)
        # validate the file
        if folder_path is not None:
            error_info, files_to_add_to_resource = raster_file_validation(raster_file=temp_file,
                                                                          raster_folder=folder_path,
                                                                          resource=resource)
        else:
            error_info, files_to_add_to_resource = raster_file_validation(raster_file=temp_file)

        if not error_info:
            msg = "Geographic raster aggregation. Error when creating aggregation. Error:{}"
            file_type_success = False
            log.info("Geographic raster aggregation validation successful.")
            # extract metadata
            temp_vrt_file_path = [os.path.join(temp_dir, f) for f in os.listdir(temp_dir) if
                                  '.vrt' == os.path.splitext(f)[1]].pop()
            metadata = extract_metadata(temp_vrt_file_path)
            log.info("Geographic raster metadata extraction was successful.")

            with transaction.atomic():
                # create a geo raster logical file object to be associated with resource files
                logical_file = cls.create()
                # by default set the dataset_name attribute of the logical file to the
                # name of the file selected to set file type
                logical_file.dataset_name = base_file_name
                logical_file.save()

                try:
                    if folder_path is None:
                        # we are here means aggregation is being created by selecting a file
                        # create a folder for the raster file type using the base file name as the
                        # name for the new folder if the file is not in a folder already
                        if file_folder is None:
                            new_folder_path = cls.compute_file_type_folder(resource, file_folder,
                                                                           base_file_name)

                            log.info("Folder created:{}".format(new_folder_path))
                            create_folder(resource.short_id, new_folder_path)
                            new_folder_name = new_folder_path.split('/')[-1]
                            upload_folder = new_folder_name
                            if res_file.extension.lower() == ".tif":
                                # copy the tif file to the new aggregation folder location
                                tgt_folder = new_folder_path[len('data/contents/'):]
                                copied_res_file = ResourceFile.create(resource=resource,
                                                                      file=None,
                                                                      folder=tgt_folder,
                                                                      source=res_file.storage_path)

                                # make the copied tif file as part of the aggregation/file type
                                logical_file.add_resource_file(copied_res_file)
                                # remove the tif file from the list of files
                                files_to_add_to_resource = [f for f in files_to_add_to_resource
                                                            if not f.endswith(res_file.file_name)]
                                logical_file.add_files_to_resource(
                                    resource=resource, files_to_add=files_to_add_to_resource,
                                    upload_folder=upload_folder)
                            else:
                                # selected file must be a zip file - add the extracted files to
                                # the resource
                                logical_file.add_files_to_resource(
                                    resource=resource, files_to_add=files_to_add_to_resource,
                                    upload_folder=upload_folder)
                        else:
                            upload_folder = file_folder
                            if res_file.extension.lower() == ".tif":
                                # make the selected tif file as part of the aggregation/file type
                                logical_file.add_resource_file(res_file)

                                # remove the tif file from the list of files
                                files_to_add_to_resource = [f for f in files_to_add_to_resource
                                                            if not f.endswith(res_file.file_name)]

                                logical_file.add_files_to_resource(
                                    resource=resource, files_to_add=files_to_add_to_resource,
                                    upload_folder=upload_folder)
                            else:
                                # selected file must be a zip file - add the extracted files to
                                # the resource
                                logical_file.add_files_to_resource(
                                    resource=resource, files_to_add=files_to_add_to_resource,
                                    upload_folder=upload_folder)
                    else:
                        # user selected a folder to create aggregation
                        upload_folder = folder_path

                        # make all the files in the selected folder as part of the aggregation
                        res_files = ResourceFile.list_folder(resource=resource, folder=folder_path,
                                                             sub_folders=False)
                        for f in res_files:
                            logical_file.add_resource_file(f)

                        # any new files must be uploaded to the resource and be made part of the
                        # aggregation

                        # filter out all the files that already exist in the selected folder
                        new_files_to_add = []
                        for f in files_to_add_to_resource:
                            if not any(f.endswith(fl.file_name) for fl in res_files):
                                new_files_to_add.append(f)

                        logical_file.add_files_to_resource(
                            resource=resource, files_to_add=new_files_to_add,
                            upload_folder=upload_folder)

                    log.info("Geographic raster aggregation type - new files were added "
                             "to the resource.")

                    # use the extracted metadata to populate file metadata
                    for element in metadata:
                        # here k is the name of the element
                        # v is a dict of all element attributes/field names and field values
                        k, v = element.items()[0]
                        logical_file.metadata.create_element(k, **v)
                    log.info("Geographic raster aggregation type - metadata was saved to DB")
                    # set resource to private if logical file is missing required metadata
                    resource.update_public_and_discoverable()
                    logical_file.create_aggregation_xml_documents()
                    # if a file was selected at the root for creating aggregation then
                    # delete this original selected file
                    if folder_path is None and res_file.extension.lower() == ".zip":
                        delete_resource_file(resource.short_id, res_file.id, user)
                        log.info("Deleted the original zip file as part of creating an "
                                 "aggregation from this zip file.")
                    elif folder_path is None and file_folder is None:
                        # tif file was selected for aggregation creation
                        # need to deleted this file as we have made a copy of it to a new folder
                        delete_resource_file(resource.short_id, res_file.id, user)

                    file_type_success = True
                except Exception as ex:
                    msg = msg.format(ex.message)
                    log.exception(msg)
                finally:
                    # remove temp dir
                    if os.path.isdir(temp_dir):
                        shutil.rmtree(temp_dir)

            if not file_type_success:
                aggregation_from_folder = folder_path is not None
                cls.cleanup_on_fail_to_create_aggregation(user, resource, upload_folder,
                                                          file_folder, aggregation_from_folder)
                raise ValidationError(msg)

        else:
            # remove temp dir
            if os.path.isdir(temp_dir):
                shutil.rmtree(temp_dir)
            err_msg = "Geographic raster aggregation type validation failed. {}".format(
                ' '.join(error_info))
            log.info(err_msg)
            raise ValidationError(err_msg)

    @classmethod
    def get_primary_resouce_file(cls, resource_files):
        """Gets a resource file that has extension .tif from the list of files *resource_files* """

        res_files = [f for f in resource_files if f.extension.lower() == '.tif']
        return res_files[0] if res_files else None


def raster_file_validation(raster_file, raster_folder=None, resource=None):
    """ Validates if the relevant files are valid for raster aggregation or raster resource type

    :param  raster_file: a temp file (extension tif or zip) retrieved from irods and stored on temp
    dir in django
    :param  raster_folder: (optional) folder in which raster file exists on irods.
    :param  resource: (optional) an instance of CompositeResource in which raster_file exits.
    If a value for raster_folder is specified then a value for resource must be specified.
    :return A list of error messages and a list of file paths for all files that belong to raster
    """

    error_info = []
    new_resource_files_to_add = []

    file_name_part, ext = os.path.splitext(os.path.basename(raster_file))
    ext = ext.lower()
    create_vrt = True
    if ext == '.tif':
        if raster_folder is not None:
            res_files = ResourceFile.list_folder(resource=resource, folder=raster_folder,
                                                 sub_folders=False)

            # check if there is already a vrt file in that folder
            vrt_files = [f for f in res_files if f.extension.lower() == ".vrt"]
            tif_files = [f for f in res_files if f.extension.lower() == ".tif"]
            if vrt_files:
                if len(vrt_files) > 1:
                    error_info.append("More than one vrt file was found.")
                    return error_info, new_resource_files_to_add
                create_vrt = False
            elif len(tif_files) != 1:
                # if there are more than one tif file, there needs to be one vrt file
                error_info.append("A vrt file is missing.")
                return error_info, new_resource_files_to_add

            # get all the resource files from irods to the temp dir where
            # the temp raster file already exist
            temp_dir = os.path.dirname(raster_file)
            for f in res_files:
                if not raster_file.endswith(f.file_name):
                    temp_file = utils.get_file_from_irods(f, temp_dir)
                    new_resource_files_to_add.append(temp_file)

        if create_vrt:
            # create the .vrt file
            try:
                temp_vrt_file_path = create_vrt_file(raster_file)
            except Exception as ex:
                error_info.append(ex.message)
            else:
                if os.path.isfile(temp_vrt_file_path):
                    new_resource_files_to_add.append(temp_vrt_file_path)

        # add the tif (raster_file) to the list - needed for validation later
        new_resource_files_to_add.append(raster_file)
    elif ext == '.zip':
        try:
            extract_file_paths = _explode_raster_zip_file(raster_file)
        except Exception as ex:
            error_info.append(ex.message)
        else:
            if extract_file_paths:
                for file_path in extract_file_paths:
                    new_resource_files_to_add.append(file_path)
    else:
        error_info.append("Invalid file mime type found.")

    if not error_info:
        if ext == ".zip":
            # in case of zip, there needs to be more than one file extracted out of the zip file
            if len(new_resource_files_to_add) < 2:
                error_info.append("Invalid zip file. Seems to contain only one file. "
                                  "Multiple tif files are expected.")
                return error_info, []

        files_ext = [os.path.splitext(path)[1].lower() for path in new_resource_files_to_add]
        if files_ext.count('.vrt') > 1:
            error_info.append("Invalid zip file. Seems to contain multiple vrt files.")
            return error_info, []

        if set(files_ext) == {'.vrt', '.tif'} and files_ext.count('.vrt') == 1:
            vrt_file_path = new_resource_files_to_add[files_ext.index('.vrt')]
            raster_dataset = gdal.Open(vrt_file_path, GA_ReadOnly)
            if raster_dataset is None:
                error_info.append('Failed to open the vrt file.')
                return error_info, []

            # check if the vrt file is valid
            try:
                raster_dataset.RasterXSize
                raster_dataset.RasterYSize
                raster_dataset.RasterCount
            except AttributeError:
                error_info.append('Raster size and band information are missing.')
                return error_info, []

            # check if the raster file numbers and names are valid in vrt file
            with open(vrt_file_path, 'r') as vrt_file:
                vrt_string = vrt_file.read()
                root = ET.fromstring(vrt_string)
                raster_file_names = [file_name.text for file_name in root.iter('SourceFilename')]

            file_names = [os.path.basename(path) for path in new_resource_files_to_add]
            file_names.pop(files_ext.index('.vrt'))

            if len(file_names) > len(raster_file_names):
                msg = 'One or more additional tif files were found which are not listed in ' \
                      'the provided {} file.'
                msg = msg.format(os.path.basename(vrt_file_path))
                error_info.append(msg)
            else:
                for vrt_ref_raster_name in raster_file_names:
                    if vrt_ref_raster_name in file_names \
                            or (os.path.split(vrt_ref_raster_name)[0] == '.' and
                                os.path.split(vrt_ref_raster_name)[1] in file_names):
                        continue
                    elif os.path.basename(vrt_ref_raster_name) in file_names:
                        msg = "Please specify {} as {} in the .vrt file, because it will " \
                              "be saved in the same folder with .vrt file in HydroShare."
                        msg = msg.format(vrt_ref_raster_name, os.path.basename(vrt_ref_raster_name))
                        error_info.append(msg)
                        break
                    else:
                        msg = "The file {tif} which is listed in the {vrt} file is missing."
                        msg = msg.format(tif=os.path.basename(vrt_ref_raster_name),
                                         vrt=os.path.basename(vrt_file_path))
                        error_info.append(msg)
                        break

        elif files_ext.count('.tif') > 1 and files_ext.count('.vrt') == 0:
            msg = "Since multiple tif files are found, a vrt file is required."
            error_info.append(msg)
            new_resource_files_to_add = []

    return error_info, new_resource_files_to_add


def extract_metadata(temp_vrt_file_path):
    metadata = []
    res_md_dict = raster_meta_extract.get_raster_meta_dict(temp_vrt_file_path)
    wgs_cov_info = res_md_dict['spatial_coverage_info']['wgs84_coverage_info']
    # add core metadata coverage - box
    if wgs_cov_info:
        box = {'coverage': {'type': 'box', 'value': wgs_cov_info}}
        metadata.append(box)

    # Save extended meta spatial reference
    orig_cov_info = res_md_dict['spatial_coverage_info']['original_coverage_info']

    # Here the assumption is that if there is no value for the 'northlimit' then there is no value
    # for the bounding box
    if orig_cov_info['northlimit'] is not None:
        ori_cov = {'OriginalCoverage': {'value': orig_cov_info}}
        metadata.append(ori_cov)

    # Save extended meta cell info
    res_md_dict['cell_info']['name'] = os.path.basename(temp_vrt_file_path)
    metadata.append({'CellInformation': res_md_dict['cell_info']})

    # Save extended meta band info
    for band_info in res_md_dict['band_info'].values():
        metadata.append({'BandInformation': band_info})
    return metadata


def create_vrt_file(tif_file):
    """ tif_file exists in temp directory - retrieved from irods """

    log = logging.getLogger()

    # create vrt file
    temp_dir = os.path.dirname(tif_file)
    tif_file_name = os.path.basename(tif_file)
    vrt_file_path = os.path.join(temp_dir, os.path.splitext(tif_file_name)[0] + '.vrt')

    with open(os.devnull, 'w') as fp:
        subprocess.Popen(['gdal_translate', '-of', 'VRT', tif_file, vrt_file_path],
                         stdout=fp,
                         stderr=fp).wait()  # need to wait

    # edit VRT contents
    try:
        tree = ET.parse(vrt_file_path)
        root = tree.getroot()
        for element in root.iter('SourceFilename'):
            element.text = tif_file_name
            element.attrib['relativeToVRT'] = '1'

        tree.write(vrt_file_path)

    except Exception as ex:
        log.exception("Failed to create/write to vrt file. Error:{}".format(ex.message))
        raise Exception("Failed to create/write to vrt file")

    return vrt_file_path


def _explode_raster_zip_file(zip_file):
    """ zip_file exists in temp directory - retrieved from irods """

    log = logging.getLogger()
    temp_dir = os.path.dirname(zip_file)
    try:
        zf = zipfile.ZipFile(zip_file, 'r')
        zf.extractall(temp_dir)
        zf.close()

        # get all the file abs names in temp_dir
        extract_file_paths = []
        for dirpath, _, filenames in os.walk(temp_dir):
            for name in filenames:
                file_path = os.path.abspath(os.path.join(dirpath, name))
                file_ext = os.path.splitext(os.path.basename(file_path))[1]
                file_ext = file_ext.lower()
                if file_ext in GeoRasterLogicalFile.get_allowed_storage_file_types():
                    shutil.move(file_path, os.path.join(temp_dir, name))
                    extract_file_paths.append(os.path.join(temp_dir, os.path.basename(file_path)))

    except Exception as ex:
        log.exception("Failed to unzip. Error:{}".format(ex.message))
        raise ex

    return extract_file_paths
