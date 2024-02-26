while true
do 
  git pull | grep -v 'Already up to date' > /dev/null 2>&1 || break
  sleep 2
done

./build_pkg_dev.sh
./reinstall_pkg_dev.sh
