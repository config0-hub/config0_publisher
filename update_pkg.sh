git pull

while true
do 
  git pull | 'Already up to date' > /dev/null 2>&1 && echo "hello"
  sleep 2
done

./build_pkg_dev.sh
./reinstall_pkg_dev.sh
