'''
@paper: GAN Prior Embedded Network for Blind Face Restoration in the Wild (CVPR2021)
@author: yangxy (yangtao9009@gmail.com)
'''
import argparse

import cv2
import numpy as np

import gpen_process
from align_faces import warp_and_crop_face, get_reference_facial_points
from face_detect.retinaface_detection import RetinaFaceDetection
from face_model.face_gan import FaceGAN
from face_parse.face_parsing import FaceParse
from sr_model.real_esrnet import RealESRNet


class FaceEnhancement(object):
    def __init__(self, base_dir='./', in_size=512, out_size=None, model=None, use_sr=True, sr_model=None, sr_scale=2,
                 channel_multiplier=2, narrow=1, key=None, device='cuda'):
        self.facedetector = RetinaFaceDetection(base_dir, device)
        self.facegan = FaceGAN(base_dir, in_size, out_size, model, channel_multiplier, narrow, key, device=device)
        self.srmodel = RealESRNet(base_dir, sr_model, sr_scale, device=device)
        self.faceparser = FaceParse(base_dir, device=device)
        self.use_sr = use_sr
        self.in_size = in_size
        self.out_size = in_size if out_size is None else out_size
        self.threshold = 0.9

        # the mask for pasting restored faces back
        self.mask = np.zeros((512, 512), np.float32)
        cv2.rectangle(self.mask, (26, 26), (486, 486), (1, 1, 1), -1, cv2.LINE_AA)
        self.mask = cv2.GaussianBlur(self.mask, (101, 101), 11)
        self.mask = cv2.GaussianBlur(self.mask, (101, 101), 11)

        self.kernel = np.array((
            [0.0625, 0.125, 0.0625],
            [0.125, 0.25, 0.125],
            [0.0625, 0.125, 0.0625]), dtype="float32")

        # get the reference 5 landmarks position in the crop settings
        default_square = True
        inner_padding_factor = 0.25
        outer_padding = (0, 0)
        self.reference_5pts = get_reference_facial_points(
            (self.in_size, self.in_size), inner_padding_factor, outer_padding, default_square)

    def mask_postprocess(self, mask, thres=20):
        mask[:thres, :] = 0
        mask[-thres:, :] = 0
        mask[:, :thres] = 0
        mask[:, -thres:] = 0
        mask = cv2.GaussianBlur(mask, (101, 101), 11)
        mask = cv2.GaussianBlur(mask, (101, 101), 11)
        return mask.astype(np.float32)

    def process(self, img, aligned=False):
        orig_faces, enhanced_faces = [], []
        if aligned:
            ef = self.facegan.process(img)
            orig_faces.append(img)
            enhanced_faces.append(ef)

            if self.use_sr:
                ef = self.srmodel.process(ef)

            return ef, orig_faces, enhanced_faces

        img_sr = None
        if self.use_sr:
            img_sr = self.srmodel.process(img)
            if img_sr is not None:
                img = cv2.resize(img, img_sr.shape[:2][::-1])

        facebs, landms = self.facedetector.detect(img)

        height, width = img.shape[:2]
        full_mask = np.zeros((height, width), dtype=np.float32)
        full_img = np.zeros(img.shape, dtype=np.uint8)

        for i, (faceb, facial5points) in enumerate(zip(facebs, landms)):
            if faceb[4] < self.threshold: continue
            fh, fw = (faceb[3] - faceb[1]), (faceb[2] - faceb[0])

            facial5points = np.reshape(facial5points, (2, 5))

            of, tfm_inv = warp_and_crop_face(img, facial5points, reference_pts=self.reference_5pts,
                                             crop_size=(self.in_size, self.in_size))

            # enhance the face
            ef = self.facegan.process(of)

            orig_faces.append(of)
            enhanced_faces.append(ef)

            # tmp_mask = self.mask
            tmp_mask = self.mask_postprocess(self.faceparser.process(ef)[0] / 255.)
            tmp_mask = cv2.resize(tmp_mask, (self.in_size, self.in_size))
            tmp_mask = cv2.warpAffine(tmp_mask, tfm_inv, (width, height), flags=3)

            if min(fh, fw) < 100:  # gaussian filter for small faces
                ef = cv2.filter2D(ef, -1, self.kernel)

            if self.in_size != self.out_size:
                ef = cv2.resize(ef, (self.in_size, self.in_size))
            tmp_img = cv2.warpAffine(ef, tfm_inv, (width, height), flags=3)

            mask = tmp_mask - full_mask
            full_mask[np.where(mask > 0)] = tmp_mask[np.where(mask > 0)]
            full_img[np.where(mask > 0)] = tmp_img[np.where(mask > 0)]

        full_mask = full_mask[:, :, np.newaxis]
        if self.use_sr and img_sr is not None:
            img = cv2.convertScaleAbs(img_sr * (1 - full_mask) + full_img * full_mask)
        else:
            img = cv2.convertScaleAbs(img * (1 - full_mask) + full_img * full_mask)

        return img, orig_faces, enhanced_faces


# python demo.py --task FaceEnhancement --model GPEN-BFR-512 --in_size 512 --channel_multiplier 2 --narrow 1 --use_sr --sr_scale 4 --use_cuda --save_face --indir examples/imgs --outdir examples/outs-bfr
def run(indir,
        outdir,
        model="GPEN-BFR-512",
        in_size=512,
        channel_multiplier=2,
        narrow=1,
        use_sr=True,
        sr_scale=4,
        sr_model="realesrnet",
        use_cuda=True,
        save_face=False):

    # parser =  argparse.ArgumentParser()
    # parser.add_argument('--model', type=str, default='GPEN-BFR-512', help='GPEN model')
    # parser.add_argument('--task', type=str, default='FaceEnhancement', help='task of GPEN model')
    # parser.add_argument('--key', type=str, default=None, help='key of GPEN model')
    # parser.add_argument('--in_size', type=int, default=512, help='in resolution of GPEN')
    # parser.add_argument('--out_size', type=int, default=None, help='out resolution of GPEN')
    # parser.add_argument('--channel_multiplier', type=int, default=2, help='channel multiplier of GPEN')
    # parser.add_argument('--narrow', type=float, default=1, help='channel narrow scale')
    # parser.add_argument('--use_sr', action='store_true', help='use sr or not')
    # parser.add_argument('--use_cuda', action='store_true', help='use cuda or not')
    # parser.add_argument('--save_face', action='store_true', help='save face or not')
    # parser.add_argument('--aligned', action='store_true', help='input are aligned faces or not')
    # parser.add_argument('--sr_model', type=str, default='realesrnet', help='SR model')
    # parser.add_argument('--sr_scale', type=int, default=2, help='SR scale')
    # parser.add_argument('--indir', type=str, default='examples/imgs', help='input folder')
    # parser.add_argument('--outdir', type=str, default='results/outs-BFR', help='output folder')

    processor = FaceEnhancement(in_size=in_size, model=model, use_sr=use_sr, sr_model=sr_model,
                                sr_scale=sr_scale, channel_multiplier=channel_multiplier, narrow=narrow,
                                key=None, device='cuda' if use_cuda else 'cpu')
    gpen_process.process(processor, indir, outdir, "FaceEnhancement", save_face=save_face)
    return outdir



