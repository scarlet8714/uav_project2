import cv2

cap = cv2.VideoCapture(0, cv2.CAP_V4L2)

cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
cap.set(cv2.CAP_PROP_FPS, 30)
cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
while True:
    ret, frame = cap.read()
    if not ret:
        break
