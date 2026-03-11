import cv2
import pytesseract

# Load the image from file
image_path = r'D:\Libraries\Desktop\New folder (3)\20240327_120005.jpg'
image = cv2.imread(image_path)

# Convert the image to grayscale
gray_image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

# Resize the image to improve OCR accuracy
scale_percent = 200  # Increase size by 200%
width = int(gray_image.shape[1] * scale_percent / 100)
height = int(gray_image.shape[0] * scale_percent / 100)
dim = (width, height)
resized_image = cv2.resize(gray_image, dim, interpolation=cv2.INTER_LINEAR)

# Apply dilation and erosion to improve text extraction
kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
dilated_image = cv2.dilate(resized_image, kernel, iterations=1)
eroded_image = cv2.erode(dilated_image, kernel, iterations=1)

# Apply adaptive thresholding
adaptive_thresh_image = cv2.adaptiveThreshold(
    eroded_image, 255,
    cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
    cv2.THRESH_BINARY, 11, 2
)

# Perform OCR on the preprocessed image
custom_config = r'--oem 3 --psm 6'
text = pytesseract.image_to_string(adaptive_thresh_image, config=custom_config)

# Print the extracted text
print(text)
