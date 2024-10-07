import os
import numpy as np
import pandas as pd
from PIL import Image
from torch.utils.data import Dataset
from torchvision import transforms
from torchvision.transforms import Resize
import matplotlib.pyplot as plt
import torch

class MultitaskDataset(Dataset):
    def __init__(self, root_dir, annotation_file,
                 transform=None,
                 rgb=True,
                 depth=True,
                 pose=False,
                 depth_folder='depth_poses',
                 rgb_folder='salient_poses',
                 pose_csv='salient_landmarks.csv',
                 target_size=(360, 640)):
        """
        Args:
            root_dir (string): Directory with 'depth' and 'rgb' folders.
            annotation_file (string): Path to the annotations CSV file.
            transform (callable, optional): Optional transform to be applied
                on the frames (both depth and RGB).
            depth_folder (string): Folder containing depth data.
            rgb_folder (string): Folder containing RGB data.
            target_size (tuple): Target size for resizing the images.
        """
        self.root_dir = root_dir
        self.transform = transform
        self.target_size = target_size
        self.resize_transform = Resize(target_size)
        self.depth = depth
        self.rgb = rgb
        self.pose = pose
        
        
        # Load the annotation file and extract the video names
        self.annotation_df = pd.read_csv(annotation_file)
        self.allowed_video_names = self.annotation_df['name'].unique()

        # List of tuples: (depth_frame_path, rgb_frame_path, class_label)
        self.frame_paths = []

        # Create a list of all video folders and corresponding class labels
        if self.depth: 
            self.depth_dir = os.path.join(root_dir, depth_folder)
        self.rgb_dir = os.path.join(root_dir, rgb_folder)

        if self.pose:
            self.pose_dir = os.path.join(root_dir, pose_csv)
            self.pose_df = pd.read_csv(self.pose_dir)
            
            # Read the poses and store them in a dictionary
            self.pose_dict = self.load_pose_dict(self.pose_df)

        for class_name in os.listdir(self.depth_dir):
            class_depth_path = os.path.join(self.depth_dir, class_name)
            class_rgb_path = os.path.join(self.rgb_dir, class_name)

            if os.path.isdir(class_depth_path) and os.path.isdir(class_rgb_path):
                for video_name in os.listdir(class_depth_path):
                    # Filter by the video names present in the annotation file
                    if video_name in self.allowed_video_names:
                        video_depth_path = os.path.join(class_depth_path, video_name)
                        video_rgb_path = os.path.join(class_rgb_path, video_name)

                        # Get all the individual frames in both the depth and RGB directories
                        depth_frames = sorted([os.path.join(video_depth_path, fname) 
                                                for fname in os.listdir(video_depth_path) 
                                                if fname.endswith('.pfm')])
                        rgb_frames = sorted([os.path.join(video_rgb_path, fname) for fname in os.listdir(video_rgb_path)])

                        # Make sure the depth and RGB frames are aligned (assuming same number of frames)
                        if len(depth_frames) == len(rgb_frames):
                            for depth_frame, rgb_frame in zip(depth_frames, rgb_frames):
                                pose_key = os.path.join(class_name, video_name, os.path.basename(rgb_frame))
                                self.frame_paths.append((depth_frame, rgb_frame, pose_key, class_name))

    def __len__(self):
        # Now the length corresponds to the total number of frames, not videos
        return len(self.frame_paths)

    def __getitem__(self, idx):
        result = dict()

        # Load paths and label for the specific frame
        depth_frame_path, rgb_frame_path, pose_key, label = self.frame_paths[idx]

        # Load depth frame (assuming .pfm format for depth)
        depth_frame, _ = self.read_pfm(depth_frame_path)
        depth_frame = self.scale_depth(depth_frame)

        # Load RGB frame
        rgb_frame = Image.open(rgb_frame_path)

        # Resize both frames to the target size
        depth_frame_resized = self.resize_transform(torch.tensor(np.copy(depth_frame)))
        rgb_frame_resized = self.resize_transform(rgb_frame)

        # Apply any other transformations if necessary
        if self.transform:
            rgb_frame_resized = self.transform(rgb_frame_resized)

        if self.rgb:
            result['rgb'] = rgb_frame_resized
        if self.depth:
            result['depth'] = depth_frame_resized
        if self.pose:
            result['pose'] = self.pose_dict[pose_key]
        
        result['label'] = label

        return result


    def read_pfm(self, filename):
        """Read a PFM file and return the image data and scale factor."""
        with open(filename, 'rb') as f:
            header = f.readline().decode('latin1').rstrip()
            if header not in ('PF', 'Pf'):
                raise ValueError('Not a PFM file.')
            color = header == 'PF'
            
            # Read dimensions
            dims_line = f.readline().decode('latin1').rstrip()
            width, height = map(int, dims_line.split())
            
            # Read scale
            scale = float(f.readline().decode('latin1').rstrip())
            big_endian = scale > 0
            if not big_endian:
                scale = -scale
                
            # Read the pixel data
            num_channels = 3 if color else 1
            data = np.fromfile(f, '<f' if not big_endian else '>f', count=width * height * num_channels)
            data = np.reshape(data, (height, width, num_channels))
            
            # Flip the image vertically to correct the orientation
            data = np.flipud(data)  

            return data, scale
    
    def scale_depth(self, depth_frame):
        # Step 1: Squeeze the depth data to remove the last dimension
        depth_data_squeezed = np.squeeze(depth_frame)  # Shape will now be (360, 640)

        # Step 2: Replace NaN or inf values with 0 or a chosen value before scaling
        depth_data_cleaned = np.nan_to_num(depth_data_squeezed, nan=0.0, posinf=0.0, neginf=0.0)

        # Step 3: Compute min and max values ignoring NaNs
        min_val = np.nanmin(depth_data_cleaned)
        max_val = np.nanmax(depth_data_cleaned)

        # Step 4: Apply Min-Max Scaling
        return (depth_data_cleaned - min_val) / (max_val - min_val)

    def visualize_depth(self, idx):
         # Load paths and label for the specific frame
        depth_frame_path, _, _, _= self.frame_paths[idx]

        # Load depth frame (assuming .pfm format for depth)
        depth_frame, _ = self.read_pfm(depth_frame_path)
        depth_frame = self.scale_depth(depth_frame) * 255  

        # Step 5: Convert to uint8 for visualization
        depth_data_uint8 = np.clip(depth_frame, 0, 255).astype(np.uint8) 

        # Step 6: Visualize using matplotlib
        plt.imshow(depth_data_uint8, cmap='gray')  
        plt.title('Min-Max Scaled Depth Image')
        plt.axis('off')
        plt.show()

    # Function to scale and clip values
    def scale_and_clip(self, df):
        # Scale x columns (divide by 640) and clip
        x_columns = df.columns[df.columns.str.endswith('_x')]
        df[x_columns] = df[x_columns].div(640).clip(lower=0, upper=1)

        # Scale y columns (divide by 360) and clip
        y_columns = df.columns[df.columns.str.endswith('_y')]
        df[y_columns] = df[y_columns].div(360).clip(lower=0, upper=1)

        return df
    
    def load_pose_dict(self, df):
        df = self.scale_and_clip(df)

        # Extract just the filename from the 'scorer' column
        df['video_name'] = df['scorer'].apply(lambda x: x.split('/')[-2])  
        df['frame_name'] = df['scorer'].apply(lambda x: x.split('/')[-1])  
        df['class'] = df['scorer'].apply(lambda x: x.split('/')[-3])  

        # Filter the DataFrame to keep only the rows with allowed video names
        filtered_df = df[df['video_name'].isin(self.allowed_video_names)]

        # Optionally, drop the 'video_name' column if no longer needed
        filtered_df = filtered_df.drop(columns=['scorer'])

        # Create a dictionary to hold the key and tensor
        pose_landmarks_dict = {}

        # Extract the relevant columns for pose landmarks
        pose_columns = filtered_df.columns[1:-2]  # All columns except class, video_name, and frame_name

        for _, row in filtered_df.iterrows():
            # Create the key
            key = f"{row['class']}/{row['video_name']}/{row['frame_name']}"
            
            # Extract the pose landmarks and convert to tensor
            landmarks = torch.tensor(row[pose_columns].values.astype(float), dtype=torch.float)
            
            # Store in dictionary
            pose_landmarks_dict[key] = landmarks

        # Output the resulting dictionary
        return pose_landmarks_dict