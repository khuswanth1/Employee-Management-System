/** Center-crop an image to a 256px JPEG: small upload, and re-encoding strips metadata and any embedded payload. */
export async function toAvatarFile(file) {
  if (!/^image\/(jpeg|png|webp)$/.test(file.type)) throw new Error('Please choose a JPEG, PNG or WebP image')
  if (file.size > 8 * 1024 * 1024) throw new Error('Please choose an image under 8 MB')
  const bmp = await createImageBitmap(file)
  const s = Math.min(bmp.width, bmp.height)
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = 256
  canvas.getContext('2d').drawImage(bmp, (bmp.width - s) / 2, (bmp.height - s) / 2, s, s, 0, 0, 256, 256)
  const blob = await new Promise((res) => canvas.toBlob(res, 'image/jpeg', 0.9))
  return new File([blob], 'avatar.jpg', { type: 'image/jpeg' })
}
