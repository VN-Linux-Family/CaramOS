#!/bin/bash
# The issue of .github/workflows/veyon-upstream.yml: "Veyon x.y.z: đã dựng và test xong", with what is left to do, or
# "Veyon x.y.z: dựng hoặc test không qua", with the step that stopped and the end of its log. Run in packages/veyon/4.11
# after the build steps, with:
#   VERSION PAGE PACKAGED SERIES  the outputs of `tools/upstream.py check`
#   OUTCOMES                      the build steps in order, e.g. "bump=success orig=success source=failure deb=skipped"
#   NUMBER                        the version's issue (a comment goes to it), empty when there is none (one is opened)
#   RUN_URL                       the run, which has the packages and the logs as artifacts
#   GH_TOKEN GH_REPO              for gh
set -euo pipefail

failed=""
for outcome in ${OUTCOMES}; do
	if [ "${outcome#*=}" != success ]; then
		failed=${outcome%%=*}
		break
	fi
done

log=""
case "${failed}" in
"") ;;
bump) where="đổi số phiên bản trong gói (\`tools/upstream.py bump\`)" ;;
orig) where="tải mã nguồn của Veyon (\`make orig\`)" ;;
source)
	where="dựng gói nguồn (\`make source\`). Thường là một bản vá trong \`debian/patches\` không còn khớp"
	log=build/source.log
	;;
deb)
	where="dựng gói như Launchpad dựng (\`make deb\`)"
	log=build/deb.log
	;;
test)
	where="test gói (\`make test\`)"
	log=$(ls -t build/test-*.log 2>/dev/null | head -n 1 || true)
	;;
*) where="${failed}" ;;
esac

body=$(mktemp)
{
	if [ -z "${failed}" ]; then
		echo "Veyon ${VERSION} đã ra: ${PAGE}"
		echo
		echo "Workflow đã dựng \`packages/veyon/4.11\` với bản này như Launchpad dựng, rồi chạy test của gói: cài mới," \
			"nâng từ Veyon 4.7.5 của Ubuntu, nâng từ bản đang có trên PPA, các bước của Phòng máy với \`veyon-cli\`." \
			"Tất cả đều qua."
		echo
		echo "Gói đã dựng, gói nguồn và nhật ký nằm ở mục Artifacts của lần chạy (giữ 30 ngày): ${RUN_URL}"
		if [ "${SERIES}" = new ]; then
			echo
			echo "Bản này đổi số thứ hai (${PACKAGED} → ${VERSION}): đọc kỹ ghi chú phát hành và thử phòng máy đầy đủ."
		fi
		echo
		echo "Việc còn lại (mục \`veyon/4.11\` trong \`packages/README.md\`):"
		echo
		echo "- [ ] \`make -C packages/veyon/4.11 bump NEW=${VERSION}\`, commit"
		echo "- [ ] Thử trên phòng máy ảo cài từ bản CaramOS mới nhất: khóa màn hình, chiếu màn hình, tin nhắn," \
			"máy cập nhật lệch nhau"
		echo "- [ ] \`make -C packages/veyon/4.11 source upload\`, chờ Launchpad dựng xong"
		echo "- [ ] Migration mới trong \`caramos-ota\` để máy Phòng máy tự lên bản này, rồi phát hành \`caramos-ota\`"
	else
		echo "Veyon ${VERSION} đã ra (${PAGE}), nhưng workflow dừng ở bước ${where}."
		echo
		echo "Nhật ký đầy đủ: ${RUN_URL}"
		if [ -n "${log}" ] && [ -f "${log}" ]; then
			echo
			echo "<details><summary>Cuối ${log#build/}</summary>"
			echo
			echo '```'
			tail -n 40 "${log}"
			echo '```'
			echo
			echo "</details>"
		fi
		echo
		echo "Sửa gói xong thì chạy lại: Actions → veyon upstream → Run workflow, version ${VERSION}, đánh dấu report."
	fi
} > "${body}"

if [ -z "${failed}" ]; then
	title="Veyon ${VERSION}: đã dựng và test xong"
else
	title="Veyon ${VERSION}: dựng hoặc test không qua"
fi
if [ -z "${NUMBER}" ]; then
	gh issue create --title "${title}" --body-file "${body}"
else
	gh issue comment "${NUMBER}" --body-file "${body}"
	gh issue edit "${NUMBER}" --title "${title}"
fi
rm -f "${body}"
