let googleMapsPromise

export function loadGoogleMaps(apiKey) {
  if (!apiKey) {
    return Promise.reject(new Error('Missing Google Maps API key.'))
  }

  if (window.google?.maps) {
    return Promise.resolve(window.google.maps)
  }

  if (googleMapsPromise) {
    return googleMapsPromise
  }

  googleMapsPromise = new Promise((resolve, reject) => {
    const callbackName = '__initGoogleMapsForAV'
    window[callbackName] = () => {
      resolve(window.google.maps)
      delete window[callbackName]
    }

    const script = document.createElement('script')
    script.src = `https://maps.googleapis.com/maps/api/js?key=${apiKey}&libraries=places&callback=${callbackName}`
    script.async = true
    script.defer = true
    script.onerror = () => {
      reject(new Error('Failed to load Google Maps script.'))
      delete window[callbackName]
    }
    document.head.appendChild(script)
  })

  return googleMapsPromise
}
